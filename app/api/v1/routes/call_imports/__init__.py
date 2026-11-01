"""CSV-driven call import routes.

Users upload a CSV plus a per-batch column mapping (CSV header -> system
field). The backend persists a CallImport batch + one CallImportRow per
line, then fans the rows out to the Celery ``imports`` queue where each
row is downloaded using the telephony credential pinned on the batch.
Exotel credentialed imports require a ``recording_url`` on every row;
direct-URL imports (no credential) also require a mapped recording URL.
"""

from __future__ import annotations

from app.services.call_imports import diarisation_route_helpers as diarisation_helpers
from app.services.call_imports import manual_audio_route_helpers as manual_audio_helpers
from app.services.call_imports import present as call_import_present
from app.services.call_imports import source_parse as call_import_source_parse

from app.api.v1.routes.call_imports._router import router

# Re-exports for tests and bulk_ops (import path stability)
CallImportParseSkip = call_import_source_parse.CallImportParseSkip
CallImportParseResult = call_import_source_parse.CallImportParseResult
parse_skips_to_json = call_import_source_parse.parse_skips_to_json
MAX_UPLOAD_BYTES = call_import_source_parse.MAX_UPLOAD_BYTES
CSV_EXTENSIONS = call_import_source_parse.CSV_EXTENSIONS
XLSX_EXTENSIONS = call_import_source_parse.XLSX_EXTENSIONS
ALLOWED_EXTENSIONS = call_import_source_parse.ALLOWED_EXTENSIONS
_file_format = call_import_source_parse._file_format
_normalize_header = call_import_source_parse._normalize_header
_parse_csv = call_import_source_parse._parse_csv
_parse_xlsx = call_import_source_parse._parse_xlsx
_parse_recording_date_cell = call_import_source_parse._parse_recording_date_cell
_parse_source_file = call_import_source_parse._parse_source_file
_apply_schema_mapping = call_import_source_parse._apply_schema_mapping
_clean_parameter_mapping = call_import_source_parse._clean_parameter_mapping
_clean_skipped_columns = call_import_source_parse._clean_skipped_columns
_resolve_schema = call_import_source_parse._resolve_schema
_validate_sheet_choice = call_import_source_parse._validate_sheet_choice
_source_s3_key = call_import_source_parse._source_s3_key
_source_content_type = call_import_source_parse._source_content_type
_build_available_sheets = call_import_source_parse._build_available_sheets
_csv_preview_sheets = call_import_source_parse._csv_preview_sheets
_xlsx_preview_sheets = call_import_source_parse._xlsx_preview_sheets
_insert_staged_call_import_record = call_import_source_parse._insert_staged_call_import_record
_parse_json_form_field = call_import_source_parse._parse_json_form_field
_raise_if_no_importable_rows = call_import_source_parse._raise_if_no_importable_rows
_parameter_is_required = call_import_source_parse._parameter_is_required

_normalize_dataset = call_import_present._normalize_dataset
_normalize_import_display_name = call_import_present._normalize_import_display_name
_imported_agent_partial_id = call_import_present._imported_agent_partial_id
_platform_agent_refs = call_import_present._platform_agent_refs
_remember_platform_agent_names = call_import_present._remember_platform_agent_names
_serialize_call_import = call_import_present._serialize_call_import
_resolve_tags = call_import_present._resolve_tags
_tag_response_payload = call_import_present._tag_response_payload
_call_import_row_list_response = call_import_present._call_import_row_list_response

MAX_AUDIO_FILES_PER_REQUEST = manual_audio_helpers.MAX_AUDIO_FILES_PER_REQUEST
_enforce_audio_upload_file_limit = manual_audio_helpers._enforce_audio_upload_file_limit
_audio_extension = manual_audio_helpers._audio_extension
_audio_content_type = manual_audio_helpers._audio_content_type
_audio_s3_key = manual_audio_helpers._audio_s3_key
_manual_audio_append_start_state = manual_audio_helpers._manual_audio_append_start_state
_prepare_audio_upload_files = manual_audio_helpers._prepare_audio_upload_files
_prepare_audio_presign_items = manual_audio_helpers._prepare_audio_presign_items
_upload_manual_audio_blobs_parallel = manual_audio_helpers._upload_manual_audio_blobs_parallel
_persist_prepared_audio_rows = manual_audio_helpers._persist_prepared_audio_rows

CANCELLED_BY_USER_ERROR = diarisation_helpers.CANCELLED_BY_USER_ERROR
_cancellable_diarisation_states = diarisation_helpers._cancellable_diarisation_states
_revoke_diarisation_task = diarisation_helpers._revoke_diarisation_task
_apply_diarisation_cancel = diarisation_helpers._apply_diarisation_cancel
_render_diarised_segments_text = diarisation_helpers._render_diarised_segments_text

from app.services.call_imports.dispatch_diagnostics import (
    build_call_import_dispatch_diagnostics,
)

from app.api.v1.routes.call_imports import (  # noqa: F401
    audio_routes,
    core_routes,
    diarisation_routes,
)

from app.core.auth.capabilities import CALLS_DELETE, CALLS_IMPORT, CALLS_VIEW
from app.core.auth.workspace_route_capabilities import apply_workspace_route_capabilities

apply_workspace_route_capabilities(
    router,
    view_capability=CALLS_VIEW,
    manage_capability=CALLS_IMPORT,
    delete_capability=CALLS_DELETE,
)

from app.api.v1.routes.call_imports.core_routes import (  # noqa: E402
    _STUCK_PENDING_ERROR_MARKERS,
    _delete_s3_objects,
    _ensure_blob_storage_enabled,
    _enqueue_row_tasks,
    _is_manual_audio_call_import,
    _is_platform_call_import,
    _is_stuck_pending_import_row,
    _locate_call_import_row_or_404,
    _materialize_rows,
    _normalize_content_modality,
    _recompute_call_import_counters,
    _resolve_telephony_integration,
    _revoke_pending_tasks,
    _validate_credentialed_import_ready,
    _validate_diarised_eval_recording_ready,
    _validate_direct_url_import_ready,
    _validate_exotel_import_ready,
    _validate_telephony_credentials_live,
    get_call_import_diarisation_prompt_default,
    platform_import_hydration_complete,
)

from app.api.v1.routes.call_imports.diarisation_routes import (  # noqa: E402
    _select_rows_for_transcription,
    cancel_call_import_diarisation,
    cancel_call_import_row_diarisation,
    toggle_call_import_row_speaker_swap,
    transcribe_call_import,
    transcribe_call_import_row,
)
