"""Прочие операции данных — фасад над физическими доменами."""
from __future__ import annotations

from web_portal.lib.db.ai import add_ai_feedback  # noqa: F401
from web_portal.lib.db.network_intensity import (  # noqa: F401
    get_network_intensity_clusters,
    get_network_intensity_clusters_dual,
    get_network_intensity_clusters_dual_daily,
)
from web_portal.lib.db.analysis_data import (  # noqa: F401
    get_analysis_assignments,
    set_analysis_assignment,
    list_analysis_assignments_since,
)
from web_portal.lib.db.online_search import (  # noqa: F401
    merge_families_by_manual_groups,
    list_archive_freq_by_note,
)
from web_portal.lib.db.seans_write import (  # noqa: F401
    was_processed,
    mark_processed,
    save_all_from_dir,
    import_folder,
    import_folder_with_client,
    import_folder_incremental,
)
from web_portal.lib.db.stats import format_ids  # noqa: F401
from web_portal.lib.db.asr import (  # noqa: F401
    add_asr_train_sample,
    list_asr_train_samples,
    create_asr_training_run,
    finish_asr_training_run,
    upsert_asr_model,
    list_asr_models,
    activate_asr_model,
    get_active_asr_model,
    get_asr_settings,
    set_asr_settings,
    add_asr_feedback,
    count_asr_feedback,
)
from web_portal.lib.db.map_shared import (  # noqa: F401
    get_map_shared_objects,
    get_map_shared_objects_all,
    save_map_shared_objects,
)

__all__ = [
    "add_ai_feedback",
    "get_network_intensity_clusters",
    "get_network_intensity_clusters_dual",
    "get_network_intensity_clusters_dual_daily",
    "get_analysis_assignments",
    "set_analysis_assignment",
    "list_analysis_assignments_since",
    "was_processed",
    "mark_processed",
    "save_all_from_dir",
    "import_folder",
    "import_folder_with_client",
    "import_folder_incremental",
    "format_ids",
    "add_asr_train_sample",
    "list_asr_train_samples",
    "create_asr_training_run",
    "finish_asr_training_run",
    "upsert_asr_model",
    "list_asr_models",
    "activate_asr_model",
    "get_active_asr_model",
    "get_asr_settings",
    "set_asr_settings",
    "add_asr_feedback",
    "count_asr_feedback",
    "get_map_shared_objects",
    "get_map_shared_objects_all",
    "save_map_shared_objects",
    "merge_families_by_manual_groups",
    "list_archive_freq_by_note",
]
