"""Сценарии домена «Админка»."""

from web_portal.application.admin.ai_agent import (
    LlmTrainingExportParams,
    assemble_ai_agent_watch_payload,
    assemble_llm_training_stats,
    execute_llm_preference_hints_export,
    execute_llm_training_export,
    parse_llm_training_export_params,
)
from web_portal.application.admin.ai_vector_index import (
    AiVectorIndexParams,
    execute_ai_vector_index,
    parse_ai_vector_index_params,
    resolve_ai_vector_db_path,
)
from web_portal.application.admin.db_health import (
    DbHealthParams,
    SeansesMultiChannelDayParams,
    execute_admin_db_health,
    execute_seanses_multi_channel_day_report,
    parse_db_health_params,
    parse_seanses_multi_channel_day_params,
    resolve_main_db_path,
)
from web_portal.application.admin.errors import AdminUseCaseHTTP
from web_portal.application.admin.export_sessions_excel import (
    iter_export_sessions_excel_events,
    resolve_export_sessions_folder,
)
from web_portal.application.admin.hubs import (
    assemble_admin_hubs_payload,
    build_hub_activity_status,
)
from web_portal.application.admin.perf_metrics import assemble_admin_perf_caches
from web_portal.application.admin.positions import (
    assemble_user_positions_map,
    parse_positions_map_assignments,
    require_user_id,
)
from web_portal.application.admin.roles import (
    assemble_admin_roles_payload,
    assemble_admin_users_list_payload,
)
from web_portal.application.admin.seans_archive import (
    ArchiveSeansesToFileParams,
    execute_archive_seanses,
    execute_archive_seanses_to_file,
    parse_archive_seanses_to_file_params,
)
from web_portal.application.admin.sync_status import assemble_admin_sync_status_payload
from web_portal.application.admin.targeting import (
    CreateTargetingInput,
    assemble_admin_targeting_list,
    execute_create_targeting,
    parse_create_targeting_input,
)

__all__ = [
    "AdminUseCaseHTTP",
    "AiVectorIndexParams",
    "ArchiveSeansesToFileParams",
    "CreateTargetingInput",
    "DbHealthParams",
    "LlmTrainingExportParams",
    "SeansesMultiChannelDayParams",
    "assemble_admin_hubs_payload",
    "assemble_admin_perf_caches",
    "assemble_admin_roles_payload",
    "assemble_admin_sync_status_payload",
    "assemble_admin_targeting_list",
    "assemble_admin_users_list_payload",
    "assemble_ai_agent_watch_payload",
    "assemble_llm_training_stats",
    "assemble_user_positions_map",
    "build_hub_activity_status",
    "execute_admin_db_health",
    "execute_ai_vector_index",
    "execute_archive_seanses",
    "execute_archive_seanses_to_file",
    "execute_create_targeting",
    "execute_llm_preference_hints_export",
    "execute_llm_training_export",
    "execute_seanses_multi_channel_day_report",
    "iter_export_sessions_excel_events",
    "parse_ai_vector_index_params",
    "parse_archive_seanses_to_file_params",
    "parse_create_targeting_input",
    "parse_db_health_params",
    "parse_llm_training_export_params",
    "parse_positions_map_assignments",
    "parse_seanses_multi_channel_day_params",
    "require_user_id",
    "resolve_ai_vector_db_path",
    "resolve_export_sessions_folder",
    "resolve_main_db_path",
]
