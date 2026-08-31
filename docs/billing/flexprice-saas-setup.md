# Flexprice SaaS setup (EfficientAI)

Usage-based billing for cloud customers. Code ingests **completion-only** events; Flexprice meters aggregate usage; plan **usage charges** turn meters into invoice lines.

## Architecture

```
App (completion events) → Flexprice meters (SUM/COUNT) → Plan usage charges → Customer invoice
         ↑
  provision_billing_customer on signup (ensure_customer)
```

Every billable event includes `workspace_id`, `feature`, and `quantity` (plus `billable_minutes` for voice). Audit IDs (`evaluation_id`, `audio_seconds`, `run_id`, etc.) are included for support traceability and do not affect meter aggregation.

## 1. Enable metering

In `config.yml` (or env):

```yaml
flexprice:
  enabled: true
  api_host: "https://us.api.flexprice.io/v1"   # or api.cloud.flexprice.io
```

Set `FLEXPRICE_API_KEY` in the environment (never commit keys).

Signup and API-key flows call `provision_billing_customer()` so each org exists in Flexprice as `external_customer_id = organization.id`. When `auto_subscribe` is enabled, new orgs also receive a subscription on `default_plan_id` (Platform plan).

```yaml
flexprice:
  enabled: true
  api_host: "https://api.cloud.flexprice.io/v1"
  auto_subscribe: true
  default_plan_id: "plan_01KVT8BTT0HRB419QVCTNHS9RV"
  default_currency: "usd"
  default_billing_period: "MONTHLY"
```

Env overrides: `FLEXPRICE_AUTO_SUBSCRIBE`, `FLEXPRICE_DEFAULT_PLAN_ID`. Leave `auto_subscribe: false` for self-hosted OSS (customer optional, no subscription).

## 2. Bootstrap meters and features

```bash
python scripts/setup_flexprice_meters.py
python scripts/setup_flexprice_meters.py --repair-call-imports   # if batch_created meters were duplicated
python scripts/setup_flexprice_meters.py --repair-playground   # archive call_evaluated + duplicate evaluation_completed meters
python scripts/setup_flexprice_meters.py --repair-features --dry-run   # preview stale feature→meter links
python scripts/setup_flexprice_meters.py --repair-features             # repoint license features (delete + recreate)
```

Flexprice feature **PUT** cannot change `meter_id`. `--repair-features` deletes and recreates each `LICENSE_FEATURES` row on the canonical published meter. **Plan usage charges on meters are not affected.**

Print the plan pricing checklist (no API):

```bash
python scripts/setup_flexprice_meters.py --plan-guide
```

## 3. Call imports — separate meters (recommended)

| Plan usage line | Meter | Aggregation | Typical price |
|-----------------|-------|-------------|---------------|
| Call import evaluations | Call Import Evaluations | SUM `quantity` | Per evaluated row |
| Call import audio | Call Import Recording Minutes | SUM `billable_minutes` | Per audio minute |
| Call import PDFs | Call Import PDF Reports | SUM `quantity` | Per report |
| Imported rows (cap) | Call Imports (feature) | SUM `quantity` | **$0** — use for tier included rows |

Do **not** put a heavy per-row price on both batch import and evaluation — customers would feel double-charged. Batch meter is for entitlements; eval + audio + PDF are paid lines.

**Audio event:** `call_import.recording_minutes_billed` fires when a row completes evaluation **and has a recording** (not on import alone).

## 4. Other products (paid usage charges)

| Product | Meter event | Unit |
|---------|-------------|------|
| Agent playground | `playground.evaluation_completed` | billable minutes |
| Test agent API | `test_agent.conversation_ended` | billable minutes |
| Voice playground | `blind_test.response_submitted`, `tts.sample_synthesized`, `tts.report_completed` | per response / sample / report |
| Evaluators | `evaluator.run_completed` + `evaluator.recording_minutes_billed` (when audio) | per run + per audio minute |
| GEPA | `prompt_optimization.run_completed` | per candidate (SUM quantity) |
| Judge alignment | `judge_alignment.run_completed` | per sample scored (SUM quantity) |
| Metrics AI assist | `metrics.ai_assist` | per request |
| Metric studio | `metric_studio.run_completed` | completed items (SUM quantity) |
| Scenario AI | `scenario.ai_text_generated` | per generation |
| Prompt partials AI | `prompt_partial.ai_assisted` | per request (generate / improve / flowchart / map) |
| Call import user insights | `call_import.user_insights_generated` | per completed generation |
| Call import prompt improvements | `call_import.prompt_improvements_generated` | per completed generation |
| Persona prompt generation | `persona.prompt_generated` | per generation |
| Agent test setup | `agent.test_setup_generated` | per API call (test prompt / scenarios / full setup) |

Observability is **not billed** — no plan usage charges for observability events.

## 5. Configure plan in Flexprice UI

1. Open your SaaS **Plan**.
2. Add **Usage charge** for each paid meter above (pick meter by name, set unit price).
3. Click **Sync Usage Charges** on the plan.
4. Assign plan to customers / refresh subscriptions after meter or price changes.

After `--repair-call-imports`, re-sync subscriptions if price IDs changed.

## 6. Smoke tests before launch

| Action | Expected event | Check quantity |
|--------|----------------|----------------|
| Materialize call import | `call_import.batch_created` | row count |
| Complete eval pass | `call_import.evaluation_completed` | delta rows |
| Eval row with ~90s audio | `call_import.recording_minutes_billed` | 2 minutes |
| Generate PDF | `call_import.pdf_report_generated` | 1 |
| Complete playground eval | `playground.evaluation_completed` | billable minutes |
| Complete evaluator run | `evaluator.run_completed` | 1 |
| Evaluator run with audio | `evaluator.recording_minutes_billed` | billable minutes |
| Complete GEPA run | `prompt_optimization.run_completed` | candidate count |
| Complete judge alignment | `judge_alignment.run_completed` | samples scored |
| Prompt partial AI generate | `prompt_partial.ai_assisted` | 1 (`mode=generate`) |
| Call import user insights completes | `call_import.user_insights_generated` | 1 |
| Persona prompt generate | `persona.prompt_generated` | 1 |
| Agent test setup generate | `agent.test_setup_generated` | 1 |

Use Flexprice **Price Lookup** with `external_customer_id = organization UUID`.

## 7. Test isolation

Pytest sets `EFFICIENTAI_PYTEST=1` and mocks all Flexprice I/O. Full suite never hits the live dashboard.

## 8. Not yet wired (post-launch)

- Flexprice entitlements replacing JWT license limits (`app/core/license.py`)
- Backfill existing orgs as Flexprice customers
- Multiple plan tiers at signup (Basic $100, reference codes, Stripe checkout)
