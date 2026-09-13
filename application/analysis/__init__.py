"""Сценарии домена «Анализ радиосетей»."""

from web_portal.application.analysis.ai_reports import (
    assemble_ai_reports_list_payload,
    execute_ai_feedback,
    parse_optional_session_id,
    parse_period_report_range,
    refresh_stale_ai_job,
)
from web_portal.application.analysis.arm_task import (
    assemble_arm_task_settings,
    execute_arm_task_apply_audio_tasks,
    execute_arm_task_settings_save,
    execute_arm_task_view,
)
from web_portal.application.analysis.assignments import (
    execute_analysis_assign,
    load_analysis_assignments_for_pair,
)
from web_portal.application.analysis.callsign_tags import (
    execute_analysis_callsign_tag_update,
)
from web_portal.application.analysis.errors import AnalysisUseCaseHTTP
from web_portal.application.analysis.full_report import (
    FullReportPeriod,
    build_full_report_job_params,
    resolve_full_report_period,
    save_full_report_graph_png,
)
from web_portal.application.analysis.graph_compare import (
    assemble_analysis_graph_compare_payload,
)
from web_portal.application.analysis.graph_dynamic import (
    assemble_analysis_graph_dynamic_live_payload,
    assemble_analysis_graph_dynamic_timeline_payload,
    assemble_analysis_graph_dynamic_window_payload,
)
from web_portal.application.analysis.graph_payload import (
    assemble_analysis_graph_payload,
    build_simple_analysis_graph,
)
from web_portal.application.analysis.graph_timeline import (
    assemble_analysis_graph_timeline_payload,
    resolve_graph_timeline_window,
)
from web_portal.application.analysis.seans_rows import collect_seans_rows
from web_portal.application.analysis.keys_check import (
    assemble_analysis_keys_check_payload,
    build_analysis_keys_sql_filter,
    parse_analysis_keys_check_range,
)
from web_portal.application.analysis.keys_helpers import (
    format_analysis_key_date,
    normalize_analysis_key_header,
)
from web_portal.application.analysis.keys_import import execute_analysis_keys_import
from web_portal.application.analysis.network_order import (
    execute_analysis_network_order_save,
    execute_analysis_network_order_shared,
    normalize_network_column_order,
)
from web_portal.application.analysis.ml_helpers import (
    ml_get_active_model_for_task,
    ml_get_setting,
    ml_get_settings_map,
    ml_heuristic_label,
    ml_match_event_label,
    ml_parse_scope_pairs,
    ml_set_setting,
    ml_setting_key,
)
from web_portal.application.analysis.ml_use_cases import (
    execute_ml_dataset_build,
    execute_ml_dataset_build_forecast,
    execute_ml_feedback,
    execute_ml_predict,
    execute_ml_predict_forecast,
    execute_ml_train,
    execute_ml_train_forecast,
)
from web_portal.application.analysis.network_summary import (
    assemble_network_summary_payload,
    execute_network_summary,
    merge_network_summary_unit_names,
    parse_analysis_custom_units,
    parse_analysis_order_list,
    parse_network_summary_range,
)
from web_portal.application.analysis.period_bounds import (
    AnalysisPeriodBounds,
    build_analysis_period_bounds,
    fmt_analysis_dt,
    msk_now_naive,
    parse_analysis_datetime,
    parse_msk_date_yyyy_mm_dd,
)
from web_portal.application.analysis.stats_payload import (
    assemble_analysis_pair_stats_rows,
    assemble_analysis_unit_stats_rows,
)

__all__ = [
    "AnalysisPeriodBounds",
    "AnalysisUseCaseHTTP",
    "FullReportPeriod",
    "assemble_ai_reports_list_payload",
    "assemble_analysis_graph_compare_payload",
    "assemble_analysis_graph_dynamic_live_payload",
    "assemble_analysis_graph_dynamic_timeline_payload",
    "assemble_analysis_graph_dynamic_window_payload",
    "assemble_analysis_graph_payload",
    "assemble_analysis_graph_timeline_payload",
    "assemble_analysis_keys_check_payload",
    "assemble_analysis_pair_stats_rows",
    "assemble_analysis_unit_stats_rows",
    "assemble_arm_task_settings",
    "assemble_network_summary_payload",
    "build_full_report_job_params",
    "build_simple_analysis_graph",
    "collect_seans_rows",
    "build_analysis_keys_sql_filter",
    "build_analysis_period_bounds",
    "execute_ai_feedback",
    "execute_analysis_assign",
    "execute_analysis_callsign_tag_update",
    "execute_analysis_keys_import",
    "execute_analysis_network_order_save",
    "execute_analysis_network_order_shared",
    "execute_arm_task_apply_audio_tasks",
    "execute_arm_task_settings_save",
    "execute_arm_task_view",
    "execute_ml_dataset_build",
    "execute_ml_dataset_build_forecast",
    "execute_ml_feedback",
    "execute_ml_predict",
    "execute_ml_predict_forecast",
    "execute_ml_train",
    "execute_ml_train_forecast",
    "execute_network_summary",
    "fmt_analysis_dt",
    "format_analysis_key_date",
    "load_analysis_assignments_for_pair",
    "merge_network_summary_unit_names",
    "ml_get_active_model_for_task",
    "ml_get_setting",
    "ml_get_settings_map",
    "ml_heuristic_label",
    "ml_match_event_label",
    "ml_parse_scope_pairs",
    "ml_set_setting",
    "ml_setting_key",
    "msk_now_naive",
    "normalize_analysis_key_header",
    "normalize_network_column_order",
    "parse_analysis_custom_units",
    "parse_analysis_datetime",
    "parse_analysis_keys_check_range",
    "parse_analysis_order_list",
    "parse_msk_date_yyyy_mm_dd",
    "parse_network_summary_range",
    "parse_optional_session_id",
    "parse_period_report_range",
    "refresh_stale_ai_job",
    "resolve_full_report_period",
    "resolve_graph_timeline_window",
    "save_full_report_graph_png",
]
