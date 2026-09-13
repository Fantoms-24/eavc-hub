"""
Построение семантического индекса для AI-чата (бланки перехватов + таблица сеансов).

Требуется: Ollama (или совместимый API) и модель эмбеддингов, напр.:
  ollama pull nomic-embed-text
Переменные: WEB_PORTAL_AI_BASE_URL, WEB_PORTAL_AI_PROVIDER=ollama, WEB_PORTAL_AI_EMBED_MODEL

Пример (из корня репозитория web_portal):
  python scripts/reindex_ai_vectors.py --db data\\main.sqlite
  python scripts/reindex_ai_vectors.py --db ... --intercepts-only --limit 200
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Как в app.py: родитель каталога web_portal в sys.path, чтобы работал import web_portal
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from web_portal.lib.db import connect, init_db, optimize_connection
from web_portal.lib.ai_vector_recall import (
    reindex_all,
    reindex_intercepts,
    reindex_seanses,
    sync_vectors_incremental,
)


def main() -> int:
    p = argparse.ArgumentParser(description="Переиндексация ai_vector_chunks (перехваты + сеансы)")
    p.add_argument("--db", type=Path, required=True, help="Путь к main.sqlite")
    p.add_argument("--intercepts-only", action="store_true")
    p.add_argument("--seanses-only", action="store_true")
    p.add_argument("--limit", type=int, default=None, help="Ограничить число строк (для теста)")
    p.add_argument(
        "--incremental",
        action="store_true",
        help="Только изменившиеся записи (недавние строки; см. max-intercepts / max-seanses)",
    )
    p.add_argument(
        "--max-intercepts",
        type=int,
        default=400,
        help="С инкрементом: сколько бланков проверить за прогон (свежие по updated_at)",
    )
    p.add_argument(
        "--max-seanses",
        type=int,
        default=800,
        help="С инкрементом: сколько строк сеансов проверить за прогон",
    )
    p.add_argument(
        "--no-prune",
        action="store_true",
        help="С инкрементом: не удалять устаревшие чанки после синка",
    )
    args = p.parse_args()

    db = Path(args.db).resolve()
    if not db.exists():
        print(f"Файл не найден: {db}", file=sys.stderr)
        return 1

    os.environ.setdefault("WEB_PORTAL_AI_PROVIDER", "ollama")
    os.environ.setdefault("WEB_PORTAL_AI_EMBED_MODEL", "nomic-embed-text")

    conn = connect(db)
    try:
        init_db(conn)
    except Exception as e:
        print(f"init_db: {e}", file=sys.stderr)
        return 1

    lim = args.limit
    if args.incremental:
        r = sync_vectors_incremental(
            conn,
            max_intercepts=args.max_intercepts,
            max_seanses=args.max_seanses,
            prune=not args.no_prune,
        )
        print(r)
        return 0

    if args.intercepts_only and args.seanses_only:
        print("Укажите только один из --intercepts-only / --seanses-only", file=sys.stderr)
        return 1
    if args.intercepts_only:
        ok, tot = reindex_intercepts(conn, limit=lim)
        print(f"Перехваты: проиндексировано {ok} из {tot}")
    elif args.seanses_only:
        ok, tot = reindex_seanses(conn, limit=lim)
        print(f"Сеансы: проиндексировано {ok} из {tot}")
    else:
        r = reindex_all(conn, intercept_limit=lim, seanses_limit=lim)
        print(
            f"Перехваты: {r['intercept_indexed']}/{r['intercept_total']}, "
            f"сеансы: {r['seanse_indexed']}/{r['seanse_total']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
