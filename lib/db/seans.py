"""Сеансы: схема, архив, запись, запросы.

Физически: ``seans_schema``, ``seans_archive``, ``seans_write``, ``seans_query``.
"""
from __future__ import annotations

from web_portal.lib.db.seans_schema import (  # noqa: F401
    init_daily_aggregates,
    init_seans_tables,
    refresh_seanses_daily_aggregates,
    refresh_seanses_daily_aggregates_for_entries,
    seanses_union_source_sql,
)
from web_portal.lib.db.seans_archive import (  # noqa: F401
    clear_seanses_by_client_name,
    archive_seanses_outside_current_day,
    archive_all_seanses_to_archive,
    init_seanses_archive_file_schema,
    archive_seanses_before_date_to_file,
    cleanup_seanses,
    resolve_seans_conn_for_queries,
)
from web_portal.lib.db.seans_write import (  # noqa: F401
    _delete_conflicting_tt_seans_rows,
    _save_seans_batch,
    _save_seans_batch_with_client,
    save_seans_entries,
    seans_entries_fully_in_database,
    _parse_seans_date_time_value,
    max_seans_date_times_by_frequency,
    scan_seanses_once,
)
from web_portal.lib.db.seans_query import (  # noqa: F401
    list_distinct_seans_frequency_groups,
    list_seans_pairs,
    count_seanses_by_code,
    count_seanses_by_code_for_unit,
    get_seanses_rows_export,
    list_active_seans_freq_groups_for_unit_name,
    seanses_datetime_extremes_for_unit_pair,
    list_seanses_ids_for_unit_pair,
    list_seanses_rows_after_rowid,
    upsert_seanses_rows_from_sync,
    list_seanses_since,
)
from web_portal.lib.db.stats import (  # noqa: F401
    _seanses_period_has_rows,
    _seans_sessions_total_for_days,
    _seans_network_pairs_for_days,
)

__all__ = [
    "init_daily_aggregates",
    "refresh_seanses_daily_aggregates",
    "refresh_seanses_daily_aggregates_for_entries",
    "seanses_union_source_sql",
    "clear_seanses_by_client_name",
    "archive_seanses_outside_current_day",
    "archive_all_seanses_to_archive",
    "init_seanses_archive_file_schema",
    "archive_seanses_before_date_to_file",
    "cleanup_seanses",
    "init_seans_tables",
    "resolve_seans_conn_for_queries",
    "list_distinct_seans_frequency_groups",
    "list_seans_pairs",
    "count_seanses_by_code",
    "count_seanses_by_code_for_unit",
    "save_seans_entries",
    "seans_entries_fully_in_database",
    "max_seans_date_times_by_frequency",
    "scan_seanses_once",
    "get_seanses_rows_export",
    "list_active_seans_freq_groups_for_unit_name",
    "seanses_datetime_extremes_for_unit_pair",
    "list_seanses_ids_for_unit_pair",
    "list_seanses_rows_after_rowid",
    "upsert_seanses_rows_from_sync",
    "list_seanses_since",
]
