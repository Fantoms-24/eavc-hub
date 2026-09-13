"""Блоки бланка перехвата: разбор текста, сверка с сохранёнными блоками, сборка текста.

Модуль намеренно не знает про базу данных: все функции чистые, чтобы поведение
сверки можно было полностью покрыть тестами. Работа с таблицей `intercept_blocks`
живёт в `lib/db.py`.

Ключевая идея: у блока есть неизменяемое удостоверение личности (UUIDv7), которое
переживает правку его текста и времени. Благодаря этому правка блока остаётся
правкой, а не парой «удалить и создать» — это то, что видит оператор в Telegram.

Сборка текста (`compose_content`) повторяет правила нормализации из
`_sort_and_normalize_only` в `lib/db.py` байт в байт: пока текст бланка остаётся
источником для всех выгрузок, расхождение здесь было бы тихой порчей данных.
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
import difflib
import hashlib
import re

# Заголовок блока — строка, целиком состоящая из времени: «13.45» или «13:45».
_TIME_COLON_RE = re.compile(r"^(\d{1,2}):(\d{2})$")
_TIME_DOT_RE = re.compile(r"^(\d{1,2})\.(\d{2})$")

# Смещение суток при сортировке: блок намного «раньше» старта смены считается
# уже следующими сутками.
ROLLOVER_MIN = 12 * 60

# Внутри одного времени сопоставляем блоки по сходству текста. Порог невысокий
# сознательно: кандидаты уже ограничены совпадающим временем, а ошибка в сторону
# «не узнали блок» безопаснее (пересоздание сообщения), чем в сторону «узнали
# чужой» (правка затёрла бы другой блок).
SIMILARITY_THRESHOLD = 0.45


def parse_time_key(line: str) -> int | None:
    """Строка целиком является временем -> минуты от полуночи, иначе None."""
    s = str(line or "").strip()
    m = _TIME_COLON_RE.match(s) or _TIME_DOT_RE.match(s)
    if not m:
        return None
    hh = int(m.group(1))
    mm = int(m.group(2))
    if 0 <= hh <= 23 and 0 <= mm <= 59:
        return hh * 60 + mm
    return None


def normalize_time_header(line: str) -> str:
    """`13:01` -> `13.01`. Прочие строки возвращаются без изменений."""
    s0 = str(line or "")
    m = _TIME_COLON_RE.match(s0.strip())
    if not m:
        return s0
    hh = int(m.group(1))
    mm = int(m.group(2))
    if not (0 <= hh <= 23 and 0 <= mm <= 59):
        return s0
    return f"{hh}.{mm:02d}"


def _trim_edges(lines: list[str]) -> list[str]:
    xs = [str(x).rstrip() for x in lines]
    while xs and xs[0].strip() == "":
        xs.pop(0)
    while xs and xs[-1].strip() == "":
        xs.pop()
    return xs


@dataclass(frozen=True)
class ParsedBlock:
    """Блок, вычитанный из текста бланка."""

    time_key: int | None
    lines: tuple[str, ...]
    ord: int

    @property
    def header(self) -> str:
        return self.lines[0] if (self.time_key is not None and self.lines) else ""

    @property
    def body(self) -> str:
        rest = self.lines[1:] if self.time_key is not None else self.lines
        return "\n".join(rest)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def text_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class StoredBlock:
    """Блок, уже лежащий в базе."""

    uuid: str
    time_key: int | None
    header: str
    body: str
    ord: int

    @property
    def lines(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.header:
            out.append(self.header)
        if self.body:
            out.extend(self.body.split("\n"))
        return tuple(out)

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


@dataclass(frozen=True)
class ResolvedBlock:
    """Итог сверки для одного входящего блока.

    `uuid is None` означает, что блок новый и идентификатор ему ещё не выдан.
    """

    uuid: str | None
    block: ParsedBlock
    changed: bool


@dataclass(frozen=True)
class ReconcileResult:
    resolved: tuple[ResolvedBlock, ...]
    removed: tuple[str, ...]

    @property
    def created_count(self) -> int:
        return sum(1 for r in self.resolved if r.uuid is None)

    @property
    def changed_count(self) -> int:
        return sum(1 for r in self.resolved if r.uuid is not None and r.changed)


def parse_blocks(text: str) -> list[ParsedBlock]:
    """Текст бланка -> блоки в порядке появления.

    Блок начинается со строки времени и тянется до следующей такой строки.
    Текст до первого времени становится блоком без времени. Блоки, у которых
    после нормализации не осталось содержимого, отбрасываются.
    """
    raw_lines = str(text or "").splitlines()

    groups: list[tuple[int | None, list[str]]] = []
    curr_key: int | None = None
    curr: list[str] = []
    for ln in raw_lines:
        k = parse_time_key(ln)
        if k is not None:
            if curr:
                groups.append((curr_key, curr))
            curr_key = k
            curr = [normalize_time_header(ln).rstrip()]
            continue
        curr.append(ln.rstrip())
    if curr:
        groups.append((curr_key, curr))

    out: list[ParsedBlock] = []
    for key, lines in groups:
        xs = _trim_edges(lines)
        if not xs:
            continue
        out.append(ParsedBlock(time_key=key, lines=tuple(xs), ord=len(out)))
    return out


def sort_key(time_key: int | None, order: int, *, base_min: int | None) -> tuple:
    """Порядок блоков в бланке: по времени, блоки без времени — в конец."""
    if time_key is None:
        return (1, 0, 10**9, order)
    day_off = 0
    if base_min is not None and (int(base_min) - int(time_key)) > ROLLOVER_MIN:
        day_off = 1
    return (0, day_off, int(time_key), order)


def day_offset(time_key: int | None, *, base_min: int | None) -> int:
    if time_key is None or base_min is None:
        return 0
    return 1 if (int(base_min) - int(time_key)) > ROLLOVER_MIN else 0


def compose_content(
    blocks: list[ParsedBlock] | list[StoredBlock], *, base_min: int | None
) -> str:
    """Блоки -> текст бланка.

    Повторяет `_sort_and_normalize_only` из `lib/db.py`: сортировка по времени,
    склейка без добавления разделителей, сжатие пустых строк до одной,
    завершающий перевод строки при непустом результате.
    """
    indexed = [
        (sort_key(b.time_key, i, base_min=base_min), b) for i, b in enumerate(blocks)
    ]
    indexed.sort(key=lambda t: t[0])

    out_lines: list[str] = []
    for _, b in indexed:
        xs = _trim_edges(list(b.lines))
        if not xs:
            continue
        out_lines.extend(xs)

    compact: list[str] = []
    empty_run = 0
    for ln in out_lines:
        if str(ln).strip() == "":
            empty_run += 1
            if empty_run > 1:
                continue
            compact.append("")
        else:
            empty_run = 0
            compact.append(str(ln).rstrip())
    while compact and str(compact[0]).strip() == "":
        compact.pop(0)
    while compact and str(compact[-1]).strip() == "":
        compact.pop()
    return "\n".join(compact).rstrip() + ("\n" if compact else "")


def _similarity(a: str, b: str) -> float:
    if a == b:
        return 1.0
    if not a and not b:
        return 1.0
    return difflib.SequenceMatcher(None, a, b).ratio()


def reconcile(
    existing: list[StoredBlock], incoming: list[ParsedBlock]
) -> ReconcileResult:
    """Сопоставляет входящие блоки с сохранёнными, сохраняя их идентификаторы.

    Правила применяются по убыванию надёжности. Ни одно из них не сопоставляет
    блоки «на глазок» через весь бланк: ошибочное узнавание чужого блока привело
    бы к затиранию сообщения в Telegram, а это хуже, чем лишнее пересоздание.

    1. Полное совпадение текста — блок не изменился.
    2. Совпадение времени: внутри одного времени пары выбираются по сходству
       текста, остаток — по порядку следования.
    3. Совпадение текста при изменившемся времени — оператор исправил время.
    """
    resolved: list[ResolvedBlock | None] = [None] * len(incoming)
    used: set[str] = set()

    # Правило 1: точное совпадение текста.
    by_text: dict[str, deque[StoredBlock]] = defaultdict(deque)
    for sb in existing:
        by_text[sb.text].append(sb)
    for i, blk in enumerate(incoming):
        queue = by_text.get(blk.text)
        while queue:
            sb = queue.popleft()
            if sb.uuid in used:
                continue
            used.add(sb.uuid)
            resolved[i] = ResolvedBlock(uuid=sb.uuid, block=blk, changed=False)
            break

    # Правило 2: то же время — сначала самые похожие пары, затем по порядку.
    pending_by_time: dict[int | None, list[int]] = defaultdict(list)
    for i, blk in enumerate(incoming):
        if resolved[i] is None:
            pending_by_time[blk.time_key].append(i)
    free_by_time: dict[int | None, list[StoredBlock]] = defaultdict(list)
    for sb in existing:
        if sb.uuid not in used:
            free_by_time[sb.time_key].append(sb)

    for time_key, idxs in pending_by_time.items():
        pool = [sb for sb in free_by_time.get(time_key, []) if sb.uuid not in used]
        if not pool:
            continue
        pairs: list[tuple[float, int, str]] = []
        for i in idxs:
            for sb in pool:
                pairs.append((_similarity(incoming[i].body, sb.body), i, sb.uuid))
        pairs.sort(key=lambda t: (-t[0], t[1], t[2]))
        for ratio, i, sb_uuid in pairs:
            if ratio < SIMILARITY_THRESHOLD:
                break
            if resolved[i] is not None or sb_uuid in used:
                continue
            used.add(sb_uuid)
            resolved[i] = ResolvedBlock(uuid=sb_uuid, block=incoming[i], changed=True)
        # Остаток с тем же временем сопоставляем по порядку следования.
        leftover = deque(sb for sb in pool if sb.uuid not in used)
        for i in idxs:
            if resolved[i] is not None or not leftover:
                continue
            sb = leftover.popleft()
            used.add(sb.uuid)
            resolved[i] = ResolvedBlock(uuid=sb.uuid, block=incoming[i], changed=True)

    # Правило 3: время исправлено, текст блока сохранился.
    free_by_body: dict[str, deque[StoredBlock]] = defaultdict(deque)
    for sb in existing:
        if sb.uuid not in used and sb.body.strip():
            free_by_body[sb.body].append(sb)
    for i, blk in enumerate(incoming):
        if resolved[i] is not None or not blk.body.strip():
            continue
        queue = free_by_body.get(blk.body)
        while queue:
            sb = queue.popleft()
            if sb.uuid in used:
                continue
            used.add(sb.uuid)
            resolved[i] = ResolvedBlock(uuid=sb.uuid, block=blk, changed=True)
            break

    # Остальное: входящие без пары — новые, сохранённые без пары — под надгробие.
    out: list[ResolvedBlock] = []
    for i, blk in enumerate(incoming):
        out.append(resolved[i] or ResolvedBlock(uuid=None, block=blk, changed=True))
    removed = tuple(sb.uuid for sb in existing if sb.uuid not in used)
    return ReconcileResult(resolved=tuple(out), removed=removed)
