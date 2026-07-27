# Live call and evaluation storage

Two parallel paths store call/evaluation data in EfficientAI. Do not conflate them.

## Path A: Live telephony, playground, and phone evals

| Table | Default location | Purpose |
|-------|------------------|---------|
| `evaluator_results` | Catalog | Header + payload columns (list/filter/sort) |
| `call_recordings` | Catalog | Header + `call_data` JSON |

Created by inbound Vobiz webhooks, playground sessions, outbound phone evals, and observability webhooks.

When **`database.sharding.enabled`** is true:

- Catalog rows gain **`shard_id`** (stamped at insert).
- Heavy fields are **dual-written** to shard tables:
  - `evaluator_result_payloads` — transcription, speaker_segments, metric_scores, call_data, audio_s3_key
  - `call_recording_payloads` — call_data
- API/worker reads **hydrate** from shards when `shard_id` is set (catalog columns remain populated during dual-write).

Routing: `SHA256(workspace_id:entity_id) mod N` over configured data shards (see `app/db_sharding/live_entity_router.py`).

## Path B: Batch CSV call imports

| Table | Location |
|-------|----------|
| `call_imports`, `call_import_evaluations`, `call_import_shard_slices` | Catalog |
| `call_import_rows`, `call_import_evaluation_rows` | Data shards |

Routing uses `(call_import_id, row_index // chunk_size)` — see [call-import-sharding](../docs-fumadocs/content/docs/advanced/call-import-sharding.mdx).

## Operations

### Enable sharding

Set `database.sharding.enabled: true` and configure `catalog_url` + `shards[]` in `config.yml`. See `config.yml.example`.

### Backfill existing live rows

```bash
python scripts/backfill_live_entity_payloads_to_shards.py [--batch-size 500] [--dry-run]
```

Stamps `shard_id` and copies heavy columns from catalog to shard payload tables.

### Monitor catalog growth

`GET /health/detail` (admin) includes `catalog_storage` row counts and approximate table sizes for `evaluator_results` and `call_recordings`.

## Key code

| Concern | Module |
|---------|--------|
| Shard routing | `app/db_sharding/live_entity_router.py` |
| Payload read/write | `app/db_sharding/live_entity_ops.py` |
| App-facing API | `app/services/live_entity_storage.py` |
| Migration | `app/migrations/058_live_entity_payload_sharding.py` |
