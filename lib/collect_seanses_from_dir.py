from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Generator
import logging
import re

logger = logging.getLogger("web_portal.collect_seanses")

CATEGORY_PATTERN = re.compile(r"\b(?:G|g)?\d{1,10}\b")
# Границы слова снижают ложные срабатывания внутри длинных чисел / мусора.
# «12345 to G13131» / «12345 to 13132»; «13131 to 13131», «13131_to_13131»;
# «13131 to G13131» — при совпадении числа с id нормализуется в group_ = T-T (см. _session_group).
ID_GROUP_PATTERN = re.compile(
    r"\b(?P<id>\d{1,10})(?:\s+to\s+|_to_)(?P<group>(?:G|g)?\d{1,10})\b", re.IGNORECASE
)
AES_KEY_PATTERN = re.compile(r"AES256\s*key\s*id\s*:\s*(\d+)", re.IGNORECASE)
VOICE_COLOR_PATTERN = re.compile(r"Voice Color code\s*:\s*(\d+)", re.IGNORECASE)
TIME_MS_PATTERN = re.compile(r"time\s*:\s*(\d+)\s*ms", re.IGNORECASE)
AMBE_WAV_NAME_PATTERN = re.compile(
    r"^(?P<freq>[\d.,]+)_(?P<date>\d{4}-\d{2}-\d{2})_"
    r"(?P<time>\d{2}-\d{2}-\d{2})(?:\s*\(\d+\))?"
    r"\.bit\.(?P<bit>\d+)-(?P<meta>.+)\.ambe\.wav$",
    re.IGNORECASE,
)
AMBE_WAV_ALT_NAME_PATTERN = re.compile(
    r"^(?P<freq>[\d.,]+)__?(?P<year>\d{4})_(?P<month>\d{2})_(?P<day>\d{2})"
    r"__?(?P<hour>\d{2})_(?P<minute>\d{2})_(?P<second>\d{2})"
    r"(?:\s*\(\d+\))?\.bit\.(?P<bit>\d+)-(?P<meta>.+)\.ambe\.wav$",
    re.IGNORECASE,
)
AMBE_WAV_AES_PATTERN = re.compile(
    r"\bAES-k(?P<aes>\d+)-(?P<color>[A-Za-z0-9]+)\b", re.IGNORECASE
)
AMBE_WAV_RAS_PATTERN = re.compile(
    r"\bRAS-(?P<id>\d+)\.(?P<group>[A-Za-z0-9]+)\b", re.IGNORECASE
)


@dataclass(frozen=True)
class SeansEntry:
    date_time: str
    frequency: str
    group: str
    id: str
    aes_key: str | None
    color_voice: str | None = None
    time_seconds: float | None = None


def parse_ambe_wav_filename(name: str | Path) -> SeansEntry | None:
    """
    Сеанс из имени AMBE/WAV без result0.

    Пример:
    151.3920_2026-05-03_03-36-48.bit.007-AES-k185-dc-RAS-15501020.207506.ambe.wav
    """
    raw_name = Path(name).name if isinstance(name, Path) else str(name or "").split("/")[-1].split("\\")[-1]
    if not raw_name.lower().endswith(".ambe.wav"):
        return None

    m = AMBE_WAV_NAME_PATTERN.match(raw_name)
    date_s = ""
    time_s = ""
    meta = ""
    freq = ""
    if m:
        freq = str(m.group("freq") or "").strip().replace(",", ".")
        date_s = str(m.group("date") or "").strip()
        time_s = str(m.group("time") or "").strip()
        meta = str(m.group("meta") or "")
    else:
        m_alt = AMBE_WAV_ALT_NAME_PATTERN.match(raw_name)
        if not m_alt:
            return None
        freq = str(m_alt.group("freq") or "").strip().replace(",", ".")
        date_s = (
            f"{m_alt.group('year')}-{m_alt.group('month')}-{m_alt.group('day')}"
        )
        time_s = (
            f"{m_alt.group('hour')}-{m_alt.group('minute')}-{m_alt.group('second')}"
        )
        meta = str(m_alt.group("meta") or "")

    ras = AMBE_WAV_RAS_PATTERN.search(meta)
    if not ras:
        return None
    correspondent_id = str(ras.group("id") or "").strip()
    group = str(ras.group("group") or "").strip()
    if not freq or not correspondent_id or not group:
        return None

    try:
        date_time = str(datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H-%M-%S"))
    except ValueError:
        return None

    aes_key = None
    color_voice = None
    aes = AMBE_WAV_AES_PATTERN.search(meta)
    if aes:
        aes_key = str(aes.group("aes") or "").strip() or None
        color_voice = str(aes.group("color") or "").strip() or None

    return SeansEntry(
        date_time=date_time,
        frequency=freq,
        group=group,
        id=correspondent_id,
        aes_key=aes_key,
        color_voice=color_voice,
        time_seconds=None,
    )


def _session_group(id_: str, raw_group: str, *, private_call: bool = False) -> str | None:
    """
    Группа для сеанса: G999 если правый номер отличается от id; совпадение
    id и правой стороны или явный DMR Private call — трубка-в-трубку («T-T»).
    Пример: «6734818 to 7854033 Private call» не является группой 7854033.
    """
    left = (id_ or "").strip()
    right = (raw_group or "").strip()
    if not left or not right:
        return None
    ru = right.upper()
    if ru.startswith("G") and len(ru) > 1 and ru[1:].isdigit():
        suffix = ru[1:]
        if left.isdigit() and int(left) == int(suffix):
            return "T-T"
        return f"G{suffix}"
    if not right.isdigit() or not left.isdigit():
        return None
    if private_call:
        return "T-T"
    if int(left) == int(right):
        return "T-T"
    return f"G{right}"


def _paragraph_is_private_call(paragraph: str) -> bool:
    return bool(re.search(r"\bPrivate\s+call\b", str(paragraph or ""), flags=re.IGNORECASE))


def _expand_session_paragraphs(block: str) -> list[str]:
    """
    В одном фрагменте после split(\"\\n\\n\") может оказаться несколько сеансов:
    между ними часто только один \\n, без пустой строки. Тогда AES-блоки склеиваются
    и re.finditer(ID_GROUP_PATTERN) пробегает весь файл — в БД появляются лишние пары
    (id, group), которых оператор не видит, открывая «один» кусок текста.
    Если в фрагменте больше одного AES256 key id — режем по границам ключевых строк.
    """
    blk = block.strip()
    if not blk:
        return []
    if len(re.findall(r"AES256\s*key\s*id\s*:", blk, flags=re.IGNORECASE)) > 1:
        pieces = re.split(r"(?=AES256\s*key\s*id\s*:)", blk, flags=re.IGNORECASE)
        return [p.strip() for p in pieces if p.strip()]
    return [blk]


def _parse_result0_path_meta(file: Path) -> tuple[str, str] | None:
    """
    Частота и date_time из пути вида:
    .../{freq}_{YYYY-MM-DD}_{HH-MM-SS}/DMR/result0.txt
    или .../{freq}_{date}_{time}/subdir/result0.txt
    Суффиксы Windows « (0)» в имени папки игнорируются.
    """
    parts = file.parts
    if len(parts) < 4:
        return None
    if parts[-2].upper() == "DMR":
        meta_folder = str(parts[-3])
    else:
        meta_folder = str(parts[-3])
    meta_folder = re.sub(r"\s*\(\d+\)\s*$", "", meta_folder.strip())
    chunks = meta_folder.split("_")
    if len(chunks) < 3:
        return None
    frequency = chunks[0].strip()
    date_s = chunks[1].strip()
    time_s = chunks[2].strip()
    if len(chunks) > 3:
        time_s = "_".join(chunks[2:]).strip()
    time_s = re.sub(r"\s*\(\d+\)\s*$", "", time_s)
    try:
        date_time = str(datetime.strptime(f"{date_s} {time_s}", "%Y-%m-%d %H-%M-%S"))
    except ValueError:
        return None
    if not frequency or not date_s:
        return None
    return frequency, date_time


def parse_result0_file(file: Path | str) -> list[SeansEntry] | None:
    if isinstance(file, str):
        file = Path(file)

    if not file.is_file():
        logger.warning("не является файлом: %s", file)
        return None

    path_meta = _parse_result0_path_meta(file)
    if not path_meta:
        logger.warning("некорректный путь: %s", file)
        return None
    frequency, date_time = path_meta

    seans_content = None
    raw = file.read_bytes()
    for enc in (
        "utf-8",
        "utf-8-sig",
        "cp1251",
        "cp866",
        "latin-1",
        "utf-16",
        "utf-16-le",
        "utf-16-be",
    ):
        try:
            seans_content = raw.decode(enc)
            break
        except Exception:
            continue
    if seans_content is None:
        try:
            seans_content = raw.decode("utf-8", errors="replace")
        except Exception:
            logger.warning("не удалось прочитать (encoding): %s", file)
            return None

    if not re.search(CATEGORY_PATTERN, seans_content):
        logger.debug("не найдены сеансы: %s", file)
        return None

    # ключ (date_time, frequency, group, id) -> (aes_key, color_voice, time_seconds)
    current_seans: dict[
        tuple[str, str, str, str],
        tuple[str | None, str | None, float | None],
    ] = {}
    for raw_block in seans_content.split("\n\n"):
        for paragraph in _expand_session_paragraphs(raw_block):
            if not paragraph:
                continue

            aeskey = re.search(AES_KEY_PATTERN, paragraph)
            aes_key = aeskey.group(1) if aeskey else None
            voice_color = None
            m = re.search(VOICE_COLOR_PATTERN, paragraph)
            if m:
                voice_color = m.group(1).strip()
            time_seconds = None
            tm = re.search(TIME_MS_PATTERN, paragraph)
            if tm:
                time_seconds = int(tm.group(1), 10) / 1000.0

            private_call = _paragraph_is_private_call(paragraph)
            for id_group in re.finditer(ID_GROUP_PATTERN, paragraph):
                id_ = str(id_group.group("id") or "").strip()
                raw_g = str(id_group.group("group") or "")
                group = _session_group(id_, raw_g, private_call=private_call)
                if not id_ or not group:
                    continue
                entry_key = (date_time, frequency, group, id_)
                prev = current_seans.get(entry_key, (None, None, None))
                new_aes = aes_key if aes_key is not None else prev[0]
                new_color = voice_color if voice_color is not None else prev[1]
                new_time = time_seconds if time_seconds is not None else prev[2]
                current_seans[entry_key] = (new_aes, new_color, new_time)

    result: list[SeansEntry] = []
    for (dt, freq, group, id_), (aes_key, color_voice, time_seconds) in current_seans.items():
        result.append(
            SeansEntry(
                date_time=dt,
                frequency=freq,
                group=group,
                id=id_,
                aes_key=aes_key,
                color_voice=color_voice,
                time_seconds=time_seconds,
            )
        )

    logger.debug("получено записей %s: %s", len(result), file)
    return result


def collect_seanses_from(folder: Path) -> Generator[list[SeansEntry], None, None]:
    for file in folder.rglob("*"):
        if not file.is_file():
            continue
        if file.name.lower() != "result0.txt":
            continue
        seans = parse_result0_file(file)
        if seans is None:
            continue
        yield seans
