# EfficientAI platform scale audit

**Date:** 26 October 2026
**Audience:** engineering, for a working discussion
**Target:** 1 million simulations a day, 1 million production calls a day, and 1 million live traces a day, at the same time, as a multi-tenant SaaS product
**How this was done:** a read of the backend (`app/`), the frontend (`frontend/src/`, about 146,000 lines), workers, sharding, and `docker-compose.yml`. This is not a load test. Every capacity number below is calculated from the caps and worker settings that ship in the repo. Measure them before treating them as a promise.

The product is deployed on Kubernetes. This repository has no Kubernetes manifests, replica counts, CPU limits, or database settings for that cluster. The numbers here are **what one replica can do with the defaults in this repo**. Multiply by the real replica count, then subtract what those replicas share: one Postgres `max_connections`, one Redis, one set of provider rate limits.

This document has four parts. **Part A** (sections 1–17) is capacity: what breaks when the numbers get large, including the infrastructure you can add later. **Part B** is the code shape: extra queries, extra downloads, and files that only grow by getting longer. **Part C** is the pattern scorecard. **Part D** is what those three parts still left out: data lifetime, lost updates, deploy safety, cost, tenant leaks, and how you know the system is sick. A new teammate has to live in that code tomorrow.

## Start here

Read this section in the meeting. Use the rest of the document as the evidence when someone asks "where?".

The code cannot carry 1 million simulations, 1 million calls, and 1 million traces a day. Adding pods will multiply whatever each request already does. Fix the request first, then add machines.

**The problems that block the target**

1. **Live traces.** One API key is allowed about 2 exports a second. The API parses every batch, uploads it, and the worker parses it again. Every few seconds the worker rereads the whole trace. Call ids are 6 digits, so the id space runs out near 900,000.
2. **Simulations.** One worker slot holds the entire run for up to 6 hours. The default fleet has two slots. A dead worker leaves the run on `RUNNING` forever. Voice calls sit inside a worker process for the whole call.
3. **Imports and judging.** A full transcribe-and-judge day lands around 150,000–350,000 calls, not 1 million. Recordings are held in memory and downloaded more than once. The chart loads every score row. Each finished row waits on a billing HTTP call.
4. **The shared platform.** Each API pod is one process, and database calls block it. Connection pools can exceed what Postgres allows as soon as workers are busy. One Redis holds the queue, the locks, and the counters. Migrations run on every pod. Uploads still use local disk.
5. **The shape of the code.** The files people must edit are thousands of lines (`call_import_evaluations.py` is 9,937, the evaluation screen is 10,368, `api.ts` is 7,066). The next feature will be pasted into those files unless the review rule changes. Two people saving the same agent overwrite each other. Nothing deletes one organisation's data.

**What we can do, in this order**

1. **Stop doing the work twice.** Do not parse a trace on the API and again in the worker. Do not download a recording three times. Do not poll a full transcript to update a counter. Do not write the same JSON to the catalog and the shard.
2. **Make one request cheap and safe.** A list returns a summary. A poll returns a status. A create sends an idempotency key. A save sends the version it read and gets a conflict instead of a silent overwrite. If Redis is down, refuse the work.
3. **Put the next feature in a new file.** One use case, one module. A new provider or metric type is a new strategy, the same way voice providers and speech-to-text clients already work. A route does not gain SQL. A page that is already over 800 lines does not gain a fetch.
4. **Then add capacity.** Connection pooler, one worker pool per queue, trace derive that only reads new spans, import slots that match the target, ClickHouse retention, object storage instead of local disk.

**What is already in good shape, and should not be rewritten**

Fair scheduling for imports. Chunked inserts. Usage counters flushed on a timer. Telephony that places the call and returns, with audio on a separate process. Trace ingest that answers 202 and keeps the raw batch in object storage. Password login that keeps tokens in memory. A large backend test suite that already runs on pull requests.

Section 16 and Part C both talk about patterns. In the meeting, use Part C9 (the ten patterns). Section 16 is the short version of the same point. Part B is the file-by-file evidence for item 3 above. Part D is the list of problems that have no sidebar item: lost updates, retention, deploys, spend, and tenant filters.

---

## How to read this

Sections follow the sidebar, top to bottom: Dashboard, Metrics, Simulations, Playground, Evaluations, Imports, Prompts, Observability, Usage, Alerting, Configurations, then login, IAM, and platform admin. Two sections come first, because every later page sits on them:

1. The target, in plain numbers.
2. The shared platform (API, workers, Postgres, Redis, files).

Each product section has the same shape:

- **What it is today** — how a click becomes a request, a queue job, and a database write.
- **What it can carry today** — a ceiling, and what hits that ceiling first.
- **Backend** — logic that will not survive the target, and the change that fixes it.
- **Frontend** — each important control (button, list, search, poll) and whether it still works when the lists get large.
- **Keep** — behaviour that is already the right shape. Do not rewrite these while fixing the rest.

Severity means:

- **Critical** — the target is impossible, or data can be wrong or lost, until this changes.
- **High** — works for a pilot, breaks for a large tenant or for many tenants at once.
- **Medium** — pain grows with the team and with data size; not the first outage.
- **Low** — cleanup that matters once the above is done.

---

## 1. The target, in plain numbers

1 million events a day is about **12 per second** on average. A SaaS day is not flat. Plan for a **10× peak**, about **120 per second**, and assume the three streams run together.

The streams are not the same kind of work:

| Stream | What "1 million a day" actually means | What has to be in flight at peak |
| --- | --- | --- |
| Text simulations | A trial is a back-and-forth of LLM calls, often around 30 seconds, plus judge calls | About 350 trials running at once |
| Voice simulations or live voice calls | A call lasts minutes. At 5 minutes each, 1 million a day is not 12 short requests | About 3,500 calls connected at once |
| Live traces | One call exports spans many times. A 3 minute call flushing every 5 seconds is about 36 HTTP exports | About 2,000 calls on average, about 400 export requests per second average, about 4,000 per second at peak |
| Imported calls | Each call is a download, often a transcription, then one or more LLM judge calls | Slot time, not request count, is the limit |

A page view is cheap next to any of those. The pages still matter: a handful of open browsers polling a heavy endpoint will take down the API that is supposed to accept the traces.

---

## 2. Shared platform

This is the box everything else runs in. If this section stays as it is, raising a cap in one product area only moves the failure to Postgres or Redis.

### What it is today

`docker-compose.yml` is a single machine:

- **API** (`eai start`): one Uvicorn process, no worker processes. Kubernetes can run more pods, but each pod is still one process, and many routes are `async` while they run synchronous database calls on that one event loop. One slow list freezes every other request on that pod, including health.
- **Media** (`eai telephony-worker`): a second single process for live voice sockets.
- **Celery workers**, all talking to the same Redis database 0:
  - `celery` + `audio-metrics`, prefork, concurrency 8
  - `platform-imports`, `import-control`, `imports`, `diarization`, `eval-control`, `evaluations` together, threads, concurrency 12
  - `usage`, threads, concurrency 4
  - `traces`, threads, concurrency 8
  - `harbor-sim`, prefork, concurrency 2
  - `platform` (alerts, cron tick, trace sweep), concurrency 2, started in the background next to Beat
- **Beat**: one process. Its schedule file lives in the container filesystem, not on a volume. A restart can double-fire jobs. If the platform worker thread dies, Beat keeps running and nothing consumes `platform`.
- **Postgres**: one server in compose. Sharding can be turned on (`database.sharding` in config). Rows are not split by organisation. Call-import rows are hashed by `(import id, row index / 500)`. Live payloads are hashed by `(workspace id, entity id)`. The catalog (users, orgs, API keys, import metadata, run rows) stays on one database. The example shards are three databases on that same Postgres, so they share connections, disk, and WAL. Sharding in that shape does not add write capacity.
- **Redis**: one node, no password, no volume, no `maxmemory` in compose. It is the broker, the result backend, the locks, the rate limits, the usage counters, and the slot leases.
- **ClickHouse**: one node, empty password, used for traces when `clickhouse.url` is set. The example config leaves that block commented out.
- **Files**: `./uploads` and `./.data` are host folders mounted into the API, the media process, and the workers. A second pod does not see another pod's disk.

Database pools are `pool_size` 10 plus overflow 20, so **30 connections per engine per process**. Prefork children each get their own. With sharding, each child also opens a pool per shard. Postgres in the compose image allows about **100 connections**. One busy audio worker can ask for more than that by itself. There is no PgBouncer, no `pool_timeout`, and no `statement_timeout`.

Every API pod runs migrations on startup (`create_all` plus the migration runner). The only lock is inside one process. Two pods starting together will apply the same schema change at once. A failure on one shard leaves shards on different schemas while the other pods keep serving.

Authenticated requests hit Postgres even when the API-key cache hits: the cache still loads the key row and the organisation. Local login does several queries per request (user, membership, credential, org) with no cache. Mutating requests authenticate twice, because the read-only middleware resolves the caller and the route resolves them again.

Uploads up to 500 MB are read fully into memory. Playback of recordings is streamed back out through the API process even when a presigned S3 URL exists.

There is no circuit breaker around LLM, speech-to-text, speech-to-synthesis, or telephony providers. Slot leases **fail open**: if Redis errors, the code treats the slot as acquired. A Redis blip removes the only global cap and, on the usage path, falls back to a Postgres insert per event.

HTTP rate limits are off unless `rate_limits.enforce` is set, and bulk import, eval, and trace routes are exempt. Trace ingest has its own limiter (section 11) and that one fails closed.

The app defaults are `DEBUG=True` and a placeholder `SECRET_KEY`. Compose falls back to a known secret if the env var is missing. A missed env var in a new cluster boots with docs exposed and a known signing key. The local `config.yml` is gitignored and contains cloud credentials; if that file was ever copied, rotate those keys. Do not commit it.

Liveness (`/health`) is cheap. Readiness runs migration checks and opens a session per database. Prometheus, when enabled, scrapes a single static API address. Workers, media, queue depth, and pool saturation are not in that scrape.

### What it can carry today

One API pod of this shape serves **tens of requests per second** of real database work, not a sustained 150. Redis itself can do 150 simple operations per second. The connection budget and the single event loop fail first.

1 million Celery tasks a day also means 1 million result keys in the same Redis, kept until the default expiry (about a day), because `task_track_started` is on and `result_expires` is not tightened.

### What has to change

**Critical. Put a connection budget in front of Postgres.** Add PgBouncer (transaction mode) and size every pool so that `(pods × processes × engines × pool)` stays under `max_connections` with headroom. Set `pool_timeout` and `statement_timeout`. Do this before raising any product cap. More replicas without this will start failing checkouts at peak.

**Critical. Stop blocking the API event loop.** Routes that call synchronous SQLAlchemy should be plain `def` endpoints, or the database work should go to a thread pool. Run more than one worker process per API pod only after pools are budgeted. Keep voice sockets on the media deployment, not on the API.

**Critical. Split Redis by job, and make it durable.** One instance (or database) for the broker, one for ephemeral counters and locks, short result expiry, AOF or a managed primary with a replica. A restart today drops queues, slot leases, usage counters, and the rebalance lock.

**Critical. Run migrations once, with a lock.** A Job that takes a Postgres advisory lock per database, then starts the API with migrations skipped. Two replicas must not both alter the schema.

**Critical. Get files off the node disk.** Every upload and every simulation artifact goes to object storage. Presign downloads. The API should not sit in the middle of the bytes. Media call state that must survive a second replica already belongs in Redis; the in-memory fallback (section 7) has to go.

**High. One worker deployment per queue.** The imports container drains six queues on 12 threads. A big import occupies every thread, and cancel/retry (`eval-control`) waits behind scoring. Prefetch 1 and late acks are already right; the missing piece is a bulkhead per queue.

**High. Beat needs a durable scheduler.** RedBeat or a database scheduler, and the platform consumer as its own deployment with a health check. Do not scale Beat past one replica.

**High. Authenticate once per request, from cache.** Trust the cached principal for its TTL. Store a hash of the API key, not the key itself (`api_keys` is looked up in plaintext). Sample `last_used` instead of writing it on the hot path. At 150 requests per second the catalog table of keys is the hottest table in the system.

**High. Fail closed when Redis is down.** Slot acquire, usage flush, and rate limits should reject or queue locally. They should not grant unlimited work and they should not write the catalog synchronously from the hot path.

**High. Per-provider circuit breaker.** A provider outage today retries (up to 40 times on some eval tasks) and fills the worker for the 30 minute task limit. Shed load before the retry budget is spent.

**Medium. Readiness should be `SELECT 1` plus Redis ping.** Schema checks belong in the migration Job, not in the load balancer probe.

**Medium. Instrument the things you will scale.** Queue age, pool checkout wait, media socket count, trace ingest lag. One scrape target named `api:8000` cannot see a second pod.

### Keep

Queue split between audio ML, imports, usage, traces, Harbor, and platform. Late acks, prefetch 1, visibility timeout above the short task limit, prefork child recycle for the ML worker. Redis Lua slot leases for import and eval fairness (the lease shape is right; the fail-open and the single integer counter are not — see Imports). Usage token counts buffered in Redis and flushed on a timer. Liveness with no I/O. API-key cache key is a hash of the secret even though the database still stores the secret.

---

## 3. Scorecard

| Section | Verdict | Ceiling with current defaults, one replica | First thing that breaks |
| --- | --- | --- | --- |
| Shared platform | Red | Tens of API requests/s; connection errors as soon as workers are busy | Postgres connections, one event loop, one Redis |
| Dashboard | Amber | The page is cheap. It also does not show the business | A failed summary looks like an empty account |
| Metrics | Amber | Fine until the metric library or the agent list is large | Whole catalog in the browser; a failed load can seed default metrics |
| Simulations | Red | Two runs at a time. Roughly 20k text trials/day at the default concurrency of 4, or about 2k voice calls/day if all 8 shared worker slots were voice | One worker slot owns the whole run; voice calls pin a worker for the whole call |
| Playground | Red for voice, amber for chat | A few dozen concurrent playground sessions before the API thread pool and the single media process fill up | Polling and audio run inside the API or one media process |
| Evaluations | Red | On the order of 150k–350k judged audio calls/day globally, not per tenant | 128 shared slots, and charts that load every row |
| Imports | Red | About 170k recording downloads/day at 16 slots and 8 seconds each. A CSV over 15 MB is rejected | Download cap, whole file in memory, billing HTTP call per row |
| Prompts | Green | Not on the million-call path | Optimization only sees 50 results |
| Observability and traces | Red | About 2 accepted trace exports per second per API key (about 170k exports/day) | The 120/minute ingest limit, then full-trace recompute |
| Usage | Amber | Counters in Redis are fine. The usage page shows the top 100 groups | A billing HTTP call on every completed import row |
| Alerting | Red once call volume is real | The 5 minute schedule is fine | Each alert loads every call JSON in its window |
| Configurations | Amber | Fine at tens of integrations. Breaks as catalogs grow | Full lists, 1,000-key S3 browse, 23 serial model-catalog calls |
| IAM, login, platform admin | Amber | Fine for hundreds of users. The platform org table stops at 200 | Long-lived tokens in `localStorage`; workspace cache mix-ups |

---

## 4. Dashboard

Route: `/`. Files: `frontend/src/pages/dashboard/Dashboard.tsx`, `app/api/v1/routes/dashboard.py`.

### What it is today

The home page is a quick-start (four setup cards) plus a summary of catalog counts: agents, personas, metrics, imports, and similar. It does not aggregate simulations, production calls, trace error rate, queue lag, or cost. The summary is cached in the browser for 60 seconds. The query key does not include the workspace id (see section 15 for why that matters on every page).

A carousel of TTS models loads the full model catalog and rotates it every 6 seconds.

### What it can carry today

The endpoint itself will not fall over at 1 million calls a day, because it does not read those calls. It also cannot answer "are we healthy right now?". People will use Observability for that, and that page is one of the expensive ones.

### Backend

**High.** The summary counts catalog rows. Add a small rollup the page can read in one query: simulations in flight, imports in flight, calls in the last hour, trace ingest lag, error rate. Compute those in the workers as counters, not by scanning call tables on each page view.

### Frontend controls

- **Quick-start cards.** Always shown. There is no "setup already done" state, so returning users scroll past onboarding on every login. Collapse them once the summary says setup is complete.
- **Summary blocks.** If the request fails, the highlights render nothing. A 500 looks the same as a brand new account. Show an error with a retry.
- **Model carousel.** It is a catalog fetch on the hottest page in the product, and it is not the user's data. Move it off the home page or load it only when the card is opened.

### Keep

A 60 second stale time on the summary. That is the right instinct. Most other pages refetch on every visit (section 15).

---

## 5. Metrics

Routes: `/metrics-management`, Metrics Studio. Files: `frontend/src/pages/metrics/MetricsManagement.tsx` (4,518 lines), `MetricsStudio.tsx`, `app/api/v1/routes/metrics.py`, `metric_studio.py`, `app/workers/tasks/evaluate_studio_run_item.py`.

### What it is today

Metrics Management is the catalog of judge metrics (score metrics and classification metrics). The page calls `listMetrics` with no page size, then search, tag filter, and sort run in the browser on that full array. The search box filters on every keystroke. The component is one file: list, create, classification editor, categories, AI generate, and prompt-partial import.

If the list comes back empty, the page seeds default metrics. The empty array is also the default while the request is in flight or after it fails, and the seed does not check `isError`. A 500 or a blip on a new workspace creates a second set of default metrics.

Scope pickers load up to 500 agents and 500 scenarios into a multi-select. Anything past 500 cannot be selected, and the UI does not say the list was cut.

Metrics Studio lets someone try a metric against calls, import rows, recordings, or evaluator results. Each source list is capped at 100 and the query keys do not include the workspace. While a studio run is active the page polls every 3 seconds. Studio items are one Celery task each, and they draw from the same global eval slot pool as production judging (128). That is fine for a handful of samples. It is not fine if someone points Studio at a large import.

The studio run detail page sets that 3 second poll twice.

### What it can carry today

Metric count is a team-size problem, not a million-call problem. A library of a few hundred metrics will make this page janky because the whole library re-renders a 4,500 line component on each character. Studio competing with production judging becomes a problem only when Studio is used as a back door to evaluate a large corpus.

### Backend

**Medium.** Keep Studio on its own small queue and its own cap so a studio experiment cannot take the 128 production slots.

**Low.** Classification metrics on the judge path are not all batched (section 8). The metric editor is where that fan-out is configured, so a metric with 10 classification questions can turn 1 million calls into 10 million LLM calls. Show that cost in the editor before save.

### Frontend controls

- **Search, tag filter, sort.** Client-side over the full list, no debounce. Move the filter to the server, debounce the input, and page the table.
- **Create / edit / AI-generate / import partial.** All live in the same component as the list. Split one component per dialog so a change to the editor does not risk the list. This is a team-growth issue: the file is already hard to review.
- **Agent and scenario scope multi-selects.** Server search with a small page, and a clear "showing the first N" state. Silent truncation means a metric is scoped to the wrong set.
- **Studio source pickers.** Same search. Include the workspace id in the query key.
- **Studio run polling.** One poll, only while the run is non-terminal, and only while the tab is visible. The run detail page should not poll the same query twice.

### Keep

Metrics Management is one of the few pages whose query key already includes the workspace id. Copy that pattern everywhere else.

---

## 6. Simulations

Sidebar: Agents, Personas, Scenarios, Tools, and the Simulations tab on an agent. This is the pre-production path: a persona talks to the customer's agent across scenarios, for several trials, and the platform scores the result.

Files: `app/api/v1/routes/simulation_runs.py`, `app/workers/tasks/run_harbor_simulation.py`, `app/services/harbor/`, `frontend/src/pages/simulations/`, `frontend/src/pages/agents/`, `personas/`, `scenarios/`, `toolConnections/`.

### What it is today

Creating a run inserts one `SimulationRun` in `QUEUED` and enqueues **one** Celery task for the whole run. That task lands on `harbor-sim`. The compose worker has concurrency **2**. The task holds its slot for the entire run, up to **6 hours**. It starts a subprocess that runs up to `n_concurrent` trials at once (default 4, maximum 32) as threads. There is not one queue item per trial, so a second replica cannot steal the remaining trials of a big run.

Each trial holds a database connection for the whole conversation. The pool is 30 connections. `n_concurrent` of 32, plus the scorer, can exhaust it. Every turn also writes the transcript. The parent task, every 5 seconds, reloads every trial row, including the heavy payload, just to update two counters (`completed` and `failed`).

If the worker dies after the run has left `QUEUED`, the redelivered task sees `RUNNING` and returns. Nothing in the scheduler reconciles simulation runs. The run stays `RUNNING` forever. The broker visibility timeout is 2 hours, which is shorter than the 6 hour task limit, so a long run is also redelivered while it is still running.

`run_id` is a random 6 digit number (`simulation_runs.py`, `randint(100000, 999999)`), with up to 100 existence checks. The space is 900,000 values, global, not per organisation. One million runs or trials does not fit. The same pattern is used for call short ids (section 11) and evaluator result ids.

LLM calls on this path have no shared rate limit, no retry budget, and no cache. A 429 fails the trial. Harbor retries the trial once, which doubles spend. Metric judging runs inline on the same thread, after the conversation. One organisation's large run consumes the provider key for everyone else.

The run's working directory is on local disk (`HARBOR_WORK_DIR`, `./.data` in compose). The tarball is built in memory and uploaded as one blob. The download endpoint loads that blob back into the API. Extra API pods without that disk cannot read trajectories. The work directory is not removed after upload.

Sharding writes the heavy JSON (transcript, scores, call data) to the catalog **and** to a shard payload. The catalog is rewritten every turn. The shard key includes the result id, so a large org's payloads do spread out. The catalog hotspot does not.

There is no per-org cap and no global cap on this queue. The fair-share leases that exist for imports are not used here.

### What it can carry today

At the default of 4 concurrent trials and about 30 seconds per trial, one Harbor replica does roughly **20,000 trials a day** if both slots stay full. At concurrency 32, if the database pool allowed it, roughly **180,000 a day**. 1 million trials a day needs on the order of **350 trials in flight**, which is several replicas at concurrency 32, plus a provider rate limit those replicas do not have.

Two long runs occupy the entire simulation fleet of one replica. A 1,000 trial run at concurrency 4 sits on one slot for hours.

Voice simulations are a different machine and are worse. See section 7.

### Backend

**Critical. One queue item per trial, with a lease.** The imports fair-dispatcher is the pattern already in the codebase. A run is a parent row; trials are leased work; any replica can take the next trial. Cap in-flight trials per workspace, per org, and globally. Reject or queue in Postgres when the cap is full, instead of `.delay()` with no limit.

**Critical. A sweeper for stuck runs.** Heartbeat on the run. If the lease expires, requeue. Set the broker visibility timeout above the task limit. Reclaim `RUNNING` when the owner is gone. Today a deploy strands every in-flight run.

**Critical. Stop holding a connection for the whole conversation.** Open a session per turn. Size the pool to the concurrency you actually run. Keep status and counters on the catalog row; write the transcript only to the shard (or to object storage).

**Critical. Replace 6 digit public ids.** Use the UUID that already exists, or a per-org sequence. The random probe is a catalog read storm as the space fills up.

**High. A Redis limiter per LLM credential, and a token ceiling per run.** When the ceiling is hit, fail the remaining trials cleanly. Do not retry a whole trial because one call returned 429.

**High. Progress counters on the run row.** The 5 second reload of every transcript exists only to count finished trials. Increment the counter when a trial finishes.

**High. Stream artifacts to object storage and delete the work dir.** The API reads trajectories from the object store, not from local disk.

**Medium. Idempotency-Key on create.** A double click inserts two runs and two multi-hour jobs. Cancel should set the flag and revoke the task id. Avoid `terminate=True` on delete unless that child is known to be this task; killing a prefork process can take the next org's job with it.

### Frontend controls

- **Agent list** (`AgentsWorkspace`, and the list in the screenshot). `listAgents` defaults to **100**. Past that, agents exist on the server and are not in the sidebar list or the global agent switcher. Search and the All / Voice / Chat filter run on whatever page came back. There is no virtualization and no "load more". The header "N total" can disagree with what is on screen once an account has more than 100 agents.
- **Select all** on that list. It selects the loaded page, not the full server set. Say so, or make it a server-side selection.
- **Search by id or name.** Debounce it and send it to the server. Filtering 100 cards in the browser hides the rest.
- **Create Agent.** Fine as a single-entity write. The wizard should not prefetch every voice bundle, integration, and model catalog up front (VoiceBundle already does that waterfall; see section 14).
- **Overview tab.** Reads one agent. Name, language, call setup, live-session hangup. This tab is cheap. Keep it that way: do not hang live run stats on it by loading every trial.
- **Test Agent / Voice Agent tabs.** Configuration of one agent. Cheap if they load that agent and the selected bundle only. They become expensive if they pull every integration and every model to populate dropdowns. Load options for the provider the user actually picks.
- **Simulations tab and New simulation.** `NewSimulationRunModal` fetches up to 500 scenarios, 500 personas, the tool catalog, and every metric when it opens. Personas are filtered to voice vs text in the browser. Past 500 the run is silently incomplete. Use server search and show that the list is truncated.
- **Run detail.** While the run is active, the page refetches the run **and every trial** every **4 seconds** (`SimulationRunDetail.tsx`). The matrix draws one cell per scenario × persona × attempt, with no windowing. A few people watching a 1,000 trial run each pull a large JSON every 4 seconds, and the API recomputes the live summary by hydrating every transcript.
  - Poll a small progress payload (status, completed, failed, eta).
  - Page or virtualize the matrix.
  - Load a transcript only when the trial drawer opens.
- **Trial drawer.** Refetches the growing transcript and the whole trajectory on a short interval, and the trajectory is a file on the API disk. Append-only events, or stop refetching once the trial leaves "in progress".
- **Personas, Scenarios, Tools pages.** Same shape: first page only (client default 100, or no page size for tools), client-side filter, no virtualization. A workspace with 120 scenarios looks like it has 100. Page on the server.

### Keep

The run status machine (`QUEUED` → `PREPARING` → `RUNNING` → `INGESTING` → terminal). The subprocess boundary, so cancel is a signal to that process and the Celery child keeps its broker connection. The `QUEUED`-only start, which is a real guard against starting the same run twice. List endpoints for runs do not recompute the live summary; only the detail view does. Payload routing hashes workspace and entity id, so simulation payloads are not all pinned to one shard.

---

## 7. Playground and live voice

Sidebar: Agent Playground, Voice Playground. Also the live call path used by voice simulations and telephony (Vobiz / Plivo / Twilio / Telnyx), because it is the same media stack.

Files: `app/api/v1/routes/playground.py`, `voice_agent.py`, `voice_playground.py`, `app/workers/tasks/run_evaluator.py`, `initiate_vobiz_outbound.py`, `app/services/testing/test_agent_bridge_service.py`, `app/services/webrtc_bridge/`, `app/services/telephony/`, `frontend/src/pages/playground/`.

### What it is today

Two different shapes are mixed together.

**Telephony outbound** is the shape to copy. The API stores a call session in Redis (1 hour TTL) and takes a pool slot (default **5 concurrent calls per organisation**). A short Celery task places the carrier call and returns. The audio socket lands on the media process. Any media replica can accept it, as long as Redis is up. On hangup, a worker merges the two WAV tracks and uploads them.

**Voice playground and the voice evaluator bridge** do the opposite. A voice evaluation runs the WebRTC or WebSocket call **inside a Celery child** (`run_evaluator` on the default `celery` queue, shared with audio metrics, concurrency 8, 30 minute task limit). One child hosts one call. The bridge gives up at 300 seconds and may then poll the provider for up to about 10 minutes. The WebRTC path that actually completes is ElevenLabs; other platforms raise. A million 5 minute voice calls a day is about **3,500 concurrent calls**, which would be on the order of 400 of these 8-slot workers, and only if audio-metric jobs were not in the same pool.

**Agent Playground web calls.** The browser owns the Vapi call. Retell and ElevenLabs are created on the server, then a FastAPI background task polls the provider for up to 5 minutes **inside the API process**, sleeping, holding a database session, with the decrypted integration key in the task arguments. The Starlette thread pool is on the order of 40 threads. Many concurrent playground users fill it.

The media server is one Uvicorn process. Audio chunks are appended to an in-memory list for the life of the call. Merge reads both WAVs and then the merged file into memory for S3. Speech-to-text, speech-to-synthesis, and VAD for the in-browser voice agent run in that same process.

If Redis errors, the telephony session falls back to a dict on that process, and the outbound pool falls back to an in-process counter. A second media pod will not see the session and will drop the call. The pool increment is get-then-set, not atomic. A missed release blocks a slot for up to 2 hours. The outbound initiate task, on error, marks the call failed and releases the slot, then retries, which places a second carrier call.

`telephony_credential_rate_limit` covers recording fetches during import. It does not cover live Vapi, ElevenLabs, Retell, or Twilio concurrency.

### What it can carry today

Telephony: tens of calls per media pod before CPU (VAD, STT, TTS) saturates a core, and only 5 outbound calls per org. Playground: tens of concurrent polls before the API thread pool is busy doing `sleep`. Voice evaluator: about **2,000 five-minute calls a day per shared worker replica**, and fewer whenever an audio-metric task takes a slot.

### Backend

**Critical. The call does not belong inside a Celery child.** Initiate and finalize in workers. The media leg lives on the media deployment, which is how telephony already works. Put a Redis cap in front of each voice provider, the same shape as the import slot leases, and fail closed when Redis is down.

**High. Atomic pool slots with a lease per call.** `INCR` (or a sorted set of call ids), release on hangup, and a sweeper for leaked slots. Raise the per-org cap as a product limit, not a hardcoded 5, if outbound is part of the million-call target.

**High. Do not retry a carrier call that already failed the session.** Retry only before the carrier accepts. Send an idempotency key.

**High. Stream recordings.** Multipart upload from a temp file. Cap the in-memory playout buffer. Run more than one media process behind the load balancer. Sticky sessions are only needed if state is still in the process; with Redis sessions they are not.

**Medium. Playground provider polling belongs in a short task or a webhook.** Pass the credential id, not the decrypted key.

### Frontend controls

- **Agent Playground lists.** While anything is in progress, the page refetches the evaluator-result list and the call-recording list every **5 seconds**. Pagination slices an array it already downloaded, so the page size does not reduce the request. The recording list defaults to 100, so an in-progress row outside that page can stop the poll early, or an old non-terminal row can make it poll forever. Poll the specific non-terminal ids.
- **Voice Playground.** Polls at 3–4 seconds, and one panel polls external responses every 15 seconds even when idle. A WebSocket client also uses a 4 second `setInterval` that keeps firing in a background tab. Gate every interval on "visible and not finished".
- **Start call / hang up.** These are fine as single actions. The risk is the background poll and the media process, not the button.
- **Sample texts and provider pickers.** Load the catalog for the selected provider, not every provider, on open.

### Keep

Short initiate task, media process, Redis session, per-org pool. That is the right design, and the voice-eval path should be moved onto it. Provider metric polls inside the live bridge use a thread, so a 30 second HTTP call does not freeze the audio loop. LLM usage is attributed per leg (test vs production) and priced, which is the base for the budgets that are still missing. Stdio MCP tools are off unless the deployment opts in; leave them off for SaaS.

---

## 8. Evaluations

Sidebar: Evaluators, Evaluation Results, Judge Alignment. Imports have their own section; they share the judge workers with this one.

Files: `app/services/evaluators/evaluator_run_service.py`, `app/workers/tasks/run_evaluator.py`, `process_evaluator_result.py`, `app/workers/tasks/helpers/llm_evaluation.py`, `app/services/evaluators/evaluator_results_aggregate.py`, `frontend/src/pages/evaluators/`, `judgeAlignment/`.

### What it is today

A suite run inserts one `EvaluatorResult` per combination and enqueues one `run_evaluator` task each, on the default queue, with no concurrency cap. The insert loop commits and probes a unique 6 digit id **per trial on the request thread**. A large suite holds the API request for the whole loop and then floods the queue.

Chat and internal-LLM trials call the simulation function, then enqueue metric scoring. Voice trials take the bridge described in section 7.

For imported calls, scoring is the fair queue: metrics that share one LLM provider, model, and credential are **one prompt and one completion**. Classification metrics on the Jev path are each their own call, so 10 classification metrics multiply the LLM bill by about 10. There is no application-level requests-per-minute limiter in front of the provider. A 429 fails the row and the task retries.

Caps in `app/config.py`:

| Pool | Default |
| --- | --- |
| Eval + transcription, global / org / workspace / one job | 128 / 128 / 100 / 75 |
| Recording fetch, global / org / workspace | 16 / 16 / 8 |

Transcription and judging **share** the 128. A job that needs both occupies the pool twice.

The results overview loads the whole filtered set into Python and builds histograms there. The results dashboard in the browser computes trends from the newest **500** rows and tells the user the rest were dropped, while still downloading full score JSON for those 500.

Judge alignment runs one serial LLM call per sample, holding a database session across the run, and it does not use the eval slot pool. Alignment sets are small, so this does not move the million-call number. A large labeled set blocks one worker for the whole run.

### What it can carry today

One LLM call at 128 slots and about 15 seconds is roughly **740,000 judge calls a day** globally, and about **430,000** for a single job capped at 75. At 30 seconds (long transcript, or transcription then LLM on the same pool) that falls to about **370,000**. Combined with the download cap, a full transcribe-and-judge day lands around **150,000–350,000 calls**, not 1 million. One tenant cannot burst past the job cap of 75, which is correct for fairness and too low for a single large daily batch unless the slot time gets much shorter.

### Backend

**High. Separate transcription slots from judge slots.** Set the job cap from the number of workers you are paying for, not from a fixed 75, once the provider limiter exists.

**High. A token bucket per provider credential.** Backoff that does not burn the row's retry budget. The slot lease is fairness between tenants. It is not a provider rate limit. 128 parallel calls to one key will trip the provider before the slot cap is the real limit.

**High. SQL aggregates for the results overview.** The same rule as import charts (section 9): do not `.all()` score documents into the API process.

**Medium. Bulk-insert a suite, then one dispatcher.** The request should not commit once per trial.

**Medium. Batch classification questions** into the same completion that score metrics already share.

**Low. Chunk judge-alignment samples** through the same fair dispatcher, so a large labeled set does not pin a worker outside the slot pool.

### Frontend controls

- **Run evaluation / run suite.** Needs a disabled state and a server-side cap error ("this org already has N runs in flight"). Today the click always enqueues.
- **Results list and dashboard.** Server-paged. The trend chart should call a bucketed endpoint (daily pass rate, latency) instead of downloading 500 full score blobs and dropping the rest in the browser.
- **Result detail.** Load one result. Do not prefetch every sibling in the run to render one page. (The simulation trial endpoint has this bug; check the evaluator detail the same way when you touch it.)
- **Filters.** If they filter a page that was already fetched, they hide rows that are on later pages. Send the filter to the server.
- **Judge Alignment screens.** Poll every 3 seconds on the evaluate screen and every 5 seconds on the dataset screen, including when idle on the dataset page. Poll only while a run is non-terminal.

### Keep

Shared-config metrics already go out as one prompt. That is the difference between 1 million and several million LLM calls, and it should stay the default for every metric type. Result list queries on the frontend are among the ones that already include the workspace id.

---

## 9. Imports

Sidebar: Imports (call imports, chat imports, schemas, tags). This is the path most likely to be asked to carry 1 million production calls a day, by CSV, by file, or by pulling history from Vapi, Retell, or ElevenLabs.

Files: `app/api/v1/routes/call_imports.py`, `app/services/call_imports/`, `app/workers/concurrency/import_dispatch.py`, `fair_import_dispatch.py`, `limits.py`, `app/workers/tasks/process_call_import_row.py`, `transcribe_call_import_row.py`, `evaluate_call_import_row.py`, `frontend/src/pages/callImports/`.

### What it is today

The current UI upload is staged, which is the right idea, and then undone by how the bytes are handled:

1. The browser posts the CSV or Excel file to the API. The client checks a **15 MB** cap and does not parse the file itself.
2. The API reads the entire upload into memory and rejects anything over 15 MB.
3. The staged path stores those bytes in S3. A worker downloads them back with a full `read()`.
4. CSV is decoded into one string buffer. Excel builds a full list of row dicts. Mapping holds every accepted row in a Python list.
5. Rows are inserted in chunks of 1,000, onto shards when sharding is on.
6. Dispatch does **not** enqueue one Celery task per row up front. A fair round-robin pulls the next pending row, capped by Redis inflight slots. This is the right design.
7. Each recording is downloaded with `httpx` and held as `response.content`, capped at 50 MB (300 MB for platform recordings). The bytes are uploaded to S3. Transcription downloads the object again into memory. The billing step may download it a third time to probe duration.
8. Evaluation is a second fair queue on the same 128 slot pool as transcription.
9. Progress is a Redis counter plus a debounced SQL count. The UI polls every 3–5 seconds and pages rows at 50 or 100.

The slot counter is a single `INCR` with a 20 minute TTL refreshed on every acquire. A crashed worker never decrements it. New acquires keep the TTL alive, so leaked slots accumulate and the cap stays "full" forever. Redis errors return success, so the cap disappears during an outage. The platform importer already has a better lease (a sorted set in `platform_import_limits.py`). The main import path does not use it.

A legacy `/upload` route still parses and inserts inside the request.

Manual audio upload reads up to **100 files × 500 MB** into the API process before S3.

Platform pulls are in better shape: time slices, cursor pages of 100, a per-task page budget, RPM tiers of 30 / 120 / 300, and Redis leases. Discovery can list about 30,000 calls a minute on the fast tier. Hydration is then capped at 64 in flight globally and 12 per import, and each recording is still fully buffered. Listing outruns storage, and the per-import lease serializes a large customer.

Re-runs and "select all matching ids" load every id into a Python list. Search uses `ILIKE '%term%'`, which cannot use a normal index. Some detail handlers still accept a `row_limit` up to **5,000** and return full row bodies, including transcripts. The UI asks for 50–100, but the API allows the expensive call.

Fair dispatch, on each tick, asks every shard for pending import ids and then runs one "next row" query per dispatched row.

### Charts, insights, export

`GET .../aggregate` loads every row's `metric_scores` from every shard into the API process and folds them in Python. The Visualizations tab polls that **every 5 seconds** while a run is in progress (`CallImportEvaluationDetail.tsx`, about 10,400 lines).

Insights, metric clusters, and PDF generation load every eval/source pair, including transcripts, into memory, then cap the LLM calls (default 200) and shuffle. The worker runs out of memory before the LLM budget matters.

CSV export can split parts, but the call site passes a part size of 2³¹, so it is one gzip. Excel is one temp file. Row reads are paged at 1,000, which is good. The write is one giant object.

On each completed audio row, the worker makes a **synchronous HTTP call to Flexprice** before it is free to take the next row. Token usage itself is buffered in Redis. The per-row billing call is not.

### What it can carry today

| Step | Ceiling at the default caps |
| --- | --- |
| Recording download, 16 slots, ~8 s each | About 170,000 recordings/day |
| Recording download, 16 slots, ~3 s each | About 460,000/day |
| One LLM judge, 128 slots, ~15 s | About 740,000/day globally, ~430,000 for one job |
| Transcribe and judge on the shared pool | About 150,000–350,000 calls/day |
| One CSV | 15 MB. Sparse rows might be 50–80k. Rows with transcripts are a few thousand |

To hold 1 million audio calls a day at 30 seconds of slot time you need on the order of **350 concurrent judge slots** and a download pool several times 16, plus streaming so those slots are not also holding 50 MB buffers. Celery enqueue of 1 million messages is not the first failure, because dispatch only fills the inflight window. That part is already right.

### Backend

**Critical. Raise the download pool and stream the bytes.** Stream to a temp file or to S3 multipart. Pass a file path to speech-to-text. Store duration once, at ingest, so billing does not download the file again. Scale download workers separately from LLM workers.

**Critical. Replace the inflight integer with a per-task lease, and fail closed.** Copy `platform_import_limits.py`. A crash must release the slot without waiting 20 minutes, and a Redis error must not mean "unlimited".

**Critical. Stop loading every score and every transcript for charts and insights.** Maintain per-metric counts as each row completes (Redis or a rollup table) and serve the chart from that. Sample rows for insights with a keyset scan. Do not join transcript text until a row is in the sample.

**Critical. Move the Flexprice call off the worker hot path.** Push the billing event into the same Redis buffer as token usage, and flush in batches. A billing outage should not hold a judge slot for an HTTP timeout. One million extra RPCs a day, each holding a worker and a database session, will not work.

**High. Presigned upload, stream-parse, drop the 15 MB cap for streamed CSV.** The API receives a small "file is staged" message. Parse from S3 in batches. Do not build the full row list. Point any leftover caller of `/upload` at the staged flow and remove the inline path.

**High. Presign manual audio.** The API records the object key. It does not receive the bytes.

**High. Decouple platform list rate from download concurrency.** Stream those recordings too. Size the hydrate pool for the target, with a per-org cap so one customer cannot take all 64.

**High. Do not harvest every id for a retry.** Keyset-page ids into the bulk insert. Replace leading-wildcard search with trigram or prefix search.

**High. Export in parts.** Keep the 1,000 row read. Emit many gzip parts. Do not offer Excel for a million-row run.

**Medium. A Redis set of imports that still have pending rows.** Claim the next row with `UPDATE … RETURNING` on the partial index that already exists. The dispatcher should not scatter-gather every shard on every tick at 12 completions a second.

**Medium. Cap list payloads.** Lower the 5,000 row max. Exclude transcript text from list responses. The UI never needed it.

**Medium. A per-provider token bucket for speech-to-text**, same as for LLM. Sarvam's batch API for long audio is the right idea for the other providers.

### Frontend controls

- **Upload CSV / upload audio / upload chat.** The browser correctly does not parse the CSV. The bytes still go through FastAPI, and the 15 MB cap is enforced in two places that can drift. Switch the button to a presigned PUT, then a small JSON call. Show progress from the object store, not from a request body the API is buffering.
- **Import detail** (`CallImportDetail.tsx`, about 5,300 lines). Rows are paged at 100. Keep that. Do not add a client-side "load all". The 5 second poll should refetch the progress counters and the current page, not the aggregate.
- **Evaluation detail** (`CallImportEvaluationDetail.tsx`, about 10,400 lines). Several polls overlap (around 3–5 seconds). The visualizations poll is the dangerous one, because it triggers the full-table aggregate. Split the file by tab. Poll the chart only while that tab is visible, and only from the rollup, not from a full scan. Stop the poll when the run is terminal.
- **Select all / bulk retry / bulk re-eval.** These must mean "all rows matching the filter on the server", processed in pages. If they collect ids in the browser, they will truncate or freeze the tab. The API already has a path that loads every id; change both sides together.
- **Search.** Debounce, server-side, no leading wildcard.
- **Schemas and tags.** Small catalogs. A full list is fine until an org has hundreds. Page them before that, using the same table component as imports, so you do not grow a second unbounded list.
- **Export button.** Disable or switch to "we will email a link" once the run is large. A single gzip download of a million transcript rows will time out in the browser and fill a disk on the API.

### Keep

Fair round-robin across workspaces, orgs, and jobs. Chunked inserts of 1,000. Partial indexes for the pending-row claim. Redis progress counters with a debounced flush, instead of `COUNT(*)` on every completion. Platform discovery is cursor-paginated and RPM-tiered. Export already reads 1,000 rows at a time. S3 already has a chunk iterator the hot path can switch to. The UI tables are server-paged. Aggregates are not fetched until the visualizations tab is open — the bug is what that tab fetches, not the fact that it waits.

---

## 10. Prompts

Sidebar: Partials, Optimization. Files: `frontend/src/pages/promptPartials/PromptPartials.tsx` (2,813 lines), `promptOptimization/`, `app/workers/tasks/run_prompt_optimization.py`, `app/services/optimization/gepa_service.py`.

### What it is today

Partials are snippets injected into judge or agent prompts. They do not add an extra LLM call by themselves. The page is one large editor. Optimization trains on **50** evaluator results, with a default budget of about 20 metric calls, and truncates transcripts to 3,000 characters. The page polls every 5 seconds.

### What it can carry today

This will not melt the cluster at 1 million calls a day. It also cannot learn from a million-call corpus, because it never reads it.

### Backend

**Low.** If optimization is meant to learn from production, sample call-import rows with an explicit cap and a keyset scan. Do not `SELECT` the full table into the trainer.

### Frontend controls

- **Partial list and editor.** Same maintainability note as Metrics: split the editor from the list before more people are in this file. The list itself is a small catalog.
- **Run optimization.** Show the sample size and the metric-call budget on the button's confirmation, so a run cannot surprise the LLM bill. Poll only while status is running.
- **Save.** Single-row write. Fine.

### Keep

A hard budget on metric calls (`max_metric_calls`). Every other LLM path should grow a ceiling like this one.

---

## 11. Observability, live traces, and production call webhooks

Sidebar: Observability Overview and Calls. This is the live ingest path: customer agents export spans while calls are happening, and carrier webhooks deliver production calls.

Files: `app/api/v1/routes/synthetic_traces.py`, `observability.py`, `telnyx_voice_webhooks.py`, `twilio_voice_webhooks.py`, `vobiz_telephony.py`, `app/services/observability/`, `app/services/synthetic_traces/` (ingest pipeline), `app/services/clickhouse/`, `app/workers/tasks/trace_tasks.py`, `frontend/src/pages/observability/`, `test-insights/`.

### What it is today

The intended ingest path is the right shape, and the default limit makes it unusable at the target:

1. `POST /api/v1/observability/traces` authenticates, then applies a Redis sliding window of **120 requests per minute per API key** (`TRACES_RATE_LIMIT_PER_MINUTE`, enforced by default). Over the limit returns 429. Redis down returns 503 (fail closed, which is correct).
2. Body cap is 4 MB (413 over that). Good.
3. `defer_parse_to_worker` still **fully parses** the OTLP body on the API, to find the workspace, before the deferred path. The worker parses it again.
4. If ClickHouse is not configured, the deferred path returns **503**. The example config has ClickHouse commented out. A stock config cannot ingest traces. The old Postgres span tables are a legacy path; turning defer off writes one JSON batch and a commit per export, which will not reach 1 million traces a day.
5. On the hot path the API resolves or mints a trace id (Redis, else a ClickHouse `FINAL` lookup), increments a Redis sequence key that **never expires**, and does a **synchronous S3 PUT** of the raw body. Then it enqueues `process_s3_otlp_batch` and returns **202**. There is no check of queue depth. If S3 or Celery fails, the client gets 503, sometimes after the object was already written.
6. The worker inserts one ClickHouse row per span. Dedup is `ReplacingMergeTree` on span id, visible only after merge or on `FINAL` reads. A retry increments `span_count` again. Derive is scheduled with a 3 second debounce. Each derive **reloads every span for the trace**, recomputes turns, and rewrites the whole header, including the turns JSON. The ClickHouse path does not schedule another derive if newer spans arrive during the read.
7. Idle close: every 30 seconds, a query of `status = open` and `last_span_at` older than 120 seconds, **`LIMIT 200`**, over `FINAL`. Those rows stay `open` until a worker finishes, so the same 200 are queued again every 30 seconds. Closing a trace does not enqueue an evaluation.
8. Call short ids are 6 digits, 900,000 values (`app/utils/call_recordings.py`), and each attempt also probes Postgres and ClickHouse. One million retained calls do not fit. Near the cap, probes hammer both databases. Trace correlation is keyed by this id.

The calls list, on each page, runs several Postgres `COUNT`s and several ClickHouse `count()` over `FINAL`, then loads `skip + limit` rows from both stores, sorts them in the API, and slices. Search filters that window in memory, so the total shrinks to the page you fetched. List queries include the turns JSON. `call_recordings` has no index on `(workspace, source, created_at)` or on agent + time. `created_at` is unindexed.

Call detail returns the full `call_data` JSON. Audio is downloaded into a buffer in the API even though the client knows how to use a presigned URL; the panel also prefetches with `?proxy=true`. An SSE exists for live transcripts, and the panel **also** polls.

Sharding dual-writes call JSON to a shard payload and still keeps the fat column on the catalog row. The catalog does not get smaller.

ClickHouse tables have no TTL. Every hot read uses `FINAL`. Span attributes are JSON strings. At this rate a year is tens of billions of span rows if you keep them forever.

Production webhooks:

| Webhook | What the request does today | Scale problem |
| --- | --- | --- |
| Telnyx voice | Signature check only on `call.initiated`. Other events return 200 with no check. The request itself calls the provider to answer and start streaming. No event-id dedup | Answer latency, unsigned events, duplicate calls under retry |
| Twilio voice | Signature checked. TwiML built from the database in the request | Fine if the handler stays this small |
| Vobiz answer | Creates evaluator result, call session, and recording inside the webhook. A retry can insert another call | Duplicates at peak |
| Vobiz events | Writes status and the full payload. Last write wins, no event id | Lost updates, no dedup |
| Vobiz recording-ready | Downloads the audio and uploads to S3 **inside the webhook** | At ~100 call endings/s the API stalls. Retries re-download until the S3 key is set |
| Meta WhatsApp, SMS | Signature, then a Redis turn-complete. No LLM in the request | This is the right size |

`finalize_telephony_recording` is the fast-ack pattern that already exists for the voice bundle. The carrier recording webhook does not use it.

Alerts on this data are in section 13. They scan the same raw rows.

### What it can carry today

The 120/minute cap is **2 accepted exports per second per API key**, about 170,000 exports a day. That is roughly 17% of one request per trace at 1 million traces a day, and about 0.05% of a 5 second flush from 2,000 concurrent calls. A single tenant stays under the limit only while it has fewer than about **10 concurrent traced calls** flushing every 5 seconds.

ClickHouse can take the row rate. The API cannot: it parses protobuf and waits on S3 on the request. Derive then multiplies the work. About 2,000 open traces / 3 seconds is on the order of **700 full-trace reads per second** average, and several thousand at peak. Idle close cannot drain a burst: 200 closes every 30 seconds, re-queued until they finish. A 20,000 call drop takes many minutes and does the work twice.

The live-turn Redis cache lives 180 seconds. Idle close is 120 seconds, but the call-id cache is about 360 seconds. A long call (hold, support) falls back to a stale header, then a cache miss mints a **second trace id** for the same call.

The orphan sweeper lists 2,000 S3 keys every 15 minutes. If workers stall past that, the rest of the batches are never replayed.

### Backend

**Critical. Raise the ingest limit to a byte or span budget per org, and keep a separate abuse limit.** 120 requests per minute per key cannot carry the product. Return 429 from **queue depth**, not from a cap that is already too small for ten concurrent calls.

**Critical. Do not parse on the API.** Require the call id and workspace on the request (header or attribute the gateway can read without a full decode). Stream the bytes to the log. Parse only in the consumer.

**Critical. Backpressure.** If the traces queue is deeper or older than a bound, return 429. Do not run derive inside the web process when the debounce lock fails (today a Redis error runs derive inline).

**Critical. Incremental derive, and stop rewriting the whole header.** A dirty flag per trace, turn state updated from new spans, header row without the span blob. Put `workspace_id` in the lookup key so the read matches the sort order. The current lookup by trace id alone does not match `ORDER BY (workspace_id, started_at, trace_uuid)`.

**Critical. Idle close as a queue, not a `FINAL` scan.** A Redis sorted set (or a state column in the primary key) of traces due to close. Mark `closing` when claimed so the same 200 are not re-queued. TTL on observations (days) and on headers (match the 90 day list window). Stop using `FINAL` on the hot path (`argMax` or a narrow header table).

**Critical. Replace 6 digit call ids** with a time-ordered 64 bit id or a UUID. Keep a short code only as a display alias, if you still want one.

**High. One cursor per stream on the calls list.** Counts from rollups. List columns that omit turns and failure blobs. Indexes on `(workspace_id, source, created_at)` and `(organization_id, agent_id, created_at)`.

**High. Presign audio. Page transcripts.** Do not buffer the WAV in the API. Do not put the transcript in the call-detail poll.

**High. Webhooks: verify every event, insert idempotently, return 200, do the rest in a worker.** Dedup on `(provider, call id, event id)`. Vobiz recording-ready should persist the URL and enqueue the finalize task that already exists. Telnyx must verify the signature on every event type, not only `call.initiated`.

**Medium. Sequence keys need a TTL.** `INCR trace:batch_seq:{uuid}` is one Redis key per trace with no expiry: about 1 million new keys a day. Set `span_count` from a unique count, or drop it. Treat the S3 key plus a content hash as the idempotency token so retries do not double-count.

**Medium. Hold the per-trace lock or retry.** Callers today proceed when the lock was not acquired. Concurrent batches lose `last_span_at`, and idle close uses a stale timestamp.

**Medium. Catalog rows stay thin.** Ids, status, timestamps on the catalog. JSON only on the shard or in object storage. The dual-write does not reduce load while the fat column is still read.

**Medium. Trace worker settings are the ML worker settings.** A 30 minute time limit and a child recycle every 20 tasks is wrong for short, numerous trace tasks. Give the traces deployment a short time limit and a high max-tasks.

**Low. A minute rollup for the overview** (call count, error rate, latency percentiles). The dashboard route does not aggregate traces. The Observability overview downloads 500 evaluator results and charts them in the browser.

### Frontend controls

- **Overview charts.** They aggregate 500 rows in the browser. Point them at the rollup. Do not raise 500 to "load more".
- **Calls list.** Page size is small (about 15), which is good, and it refetches **every 3 seconds whenever any call is live**, with `staleTime: 0`. Each refetch reruns the hub counts. One live call makes every open Calls tab expensive. Poll a cheap generation counter, or use the SSE you already have, and refetch the list only when the generation changes.
- **Call detail.** Polls the call every 3 seconds and also opens an SSE. Pick one. Prefetch audio only as a presigned URL, not `?proxy=true`.
- **Trace panel.** Polls the trace and **all spans** every 3 seconds while the trace is open. A trace with thousands of spans is parsed in the browser on that interval. There is no virtualization. Poll spans only on the spans tab, and virtualize the list.
- **Search and filters on Calls.** They must be server filters. An in-memory filter on the fetched window reports the wrong total.
- **Evaluate on a call.** Single action, enqueue, return. Do not run the judge in the request. Confirm the button already does that; the ingest path does not evaluate on close, so this button is the manual path and should share the eval slot pool rather than bypassing it.
- **Date range.** Default the list to the 90 day window the API already has, and require an explicit action to go wider.

### Keep

202 plus an S3 write-ahead log plus a consumer is the right architecture. The 4 MB body cap is real. Trace rate limiting fails closed. ClickHouse is partitioned by month and observations dedupe by span id on merge. A cursor list API for traces already exists; the calls hub simply does not use it. Derive and close are already separate tasks on a `traces` queue. Live transcripts have Redis pub/sub SSE. SMS and WhatsApp webhooks only touch Redis. Shard payload reads for a page are grouped by shard. The API-key cache TTL for this path is configurable.

The work is to stop doing extra work on the request, and to stop rereading the world on every derive, list, and sweep.

---

## 12. Usage and billing

Route: `/usage`. Files: `frontend/src/pages/usage/Usage.tsx` (about 1,470 lines), `app/api/v1/routes/org_usage.py`, `usage_pricing.py`, `app/services/usage/llm_usage.py`, `app/services/billing/flexprice_service.py`, `app/workers/tasks/flush_usage_counters.py`.

### What it is today

LLM, speech-to-text, and speech-to-synthesis usage is a Redis hash increment, flushed to Postgres about every 120 seconds by a beat task. Two flushers are guarded by a claim script so they do not double-apply. That design can take 1 million events a day.

The exception is Flexprice: every completed import row with audio makes a synchronous HTTP ingest (section 9). On a Redis error, each usage event inserts into Postgres immediately, on the hot path.

The Usage page sets `staleTime: 0`, refetches on every mount, and refetches on window focus, overriding the global default. Breakdown requests use `limit: 100`. The page does say when the result was truncated, so the missing groups are visible, and the numbers above the cut are not. Filter changes refetch the summary, the breakdown, and the whole option catalog. The client filters those options again and regroups the already-truncated rows. Pricing loads every AI provider and the model catalog up front.

### What it can carry today

The counter path is not the bottleneck. The page is wrong as a cost report once an org has more than 100 groups (agents, metrics, days). The Flexprice call is the bottleneck, and it sits on the eval worker, not on this page.

### Backend

**Critical.** Batch billing events. Covered in Imports; it is the same code. Do not add a second per-call HTTP client here.

**High.** The breakdown API should group and page. The top 100 is a sample, and the UI should not have to regroup it.

**Low.** Orphan recovery scans Redis with `SCAN` on the broker. Fine today. If flush claims leak, do that scan on the cache instance, not on the broker, once Redis is split (section 2).

### Frontend controls

- **Date range, group-by, filters.** Cache the option lists. Do not refetch the world on focus. One request per visible breakdown, server-grouped, with a real next page.
- **Searchable selects.** They filter the 100 returned options in the browser. If the agent you want is not in the top 100, you cannot pick them. Server search.
- **Pricing tab.** Load models for the provider being edited.
- **Export.** If you add one, generate it server-side. Do not download every usage row into the table first.

### Keep

`HINCRBY` plus a timer flush plus a claim script. This is the pattern Flexprice, aggregates, and alert counts should follow.

---

## 13. Alerting

Routes: `/alerts`, `/alerts/history`. Files: `frontend/src/pages/alerting/`, `app/workers/tasks/evaluate_alerts.py`, `evaluate_alerts_for_org.py`, `app/services/alerts/`, production metric queries.

### What it is today

Beat runs alert evaluation every 5 minutes and fans out one task per organisation that has an active alert. The schedule is fine. The query is not: production alerts load **every** `CallRecording` in the window into Python and compute duration and success from `call_data`. A 60 minute window at 1 million calls a day is about 40,000 JSON rows. A 24 hour window is about 1 million. Trace alerts run `count()` on `call_traces FINAL` per alert, so each extra alert repeats the scan.

The alerts page calls `listAlerts()` with no limit, filters search and status in memory, and has no error state. A 500 looks like "no alerts configured". **Evaluate all** fires every rule from the browser. The agent multi-select uses the 100 agent cap. The query key has no workspace id.

Alert history requests `skip 0, limit 100` and treats it as fresh forever (`staleTime: Infinity`). Search filters that page. The resolved and notify-failed counts are counts of those 100 rows. Open incidents correctly use a summary endpoint. Manual refresh has a 15 second cooldown, which is good.

Alert detail loads the alert, up to 100 history rows, and all agents (capped at 100).

Readers see create, delete, and evaluate-all. The API is expected to reject them. The UI does not check the role.

### What it can carry today

Hundreds of alert rules are fine. The evaluator falls over when the call window is large, which is exactly when you want alerts.

### Backend

**High. Aggregate in SQL or ClickHouse, one scan per org per tick.** Do not materialize `call_data` to compute a rate. Reuse the rollup from section 11 if you build it; do not scan raw calls a second way.

**Medium. Evaluate-all should be one server call** for the current filter, queued, not N browser requests.

### Frontend controls

- **Search and status filter.** Server-side, paged.
- **Create, edit, delete, evaluate, evaluate all.** Hide them for readers. Show the API error instead of an empty list.
- **Agent scope.** Same typeahead as everywhere else, not the first 100 agents.
- **History table and the stat cards.** Cursor pagination. Stats from the summary endpoint, the way open incidents already work. Keep the 15 second refresh cooldown.
- **PagerDuty / email / Slack fields on the detail page.** Single-alert writes. Fine. Do not log routing keys to the console or to a toast.

### Keep

The 5 minute coordinator, the per-org fan-out, the open-incident summary endpoint, and the history refresh cooldown. Those are the right size. The metric query under them is what has to change.

---

## 14. Configurations

Sidebar: Cloud Storage, VoiceBundle, Integrations, Telephony Numbers, API Keys, Cron Jobs. Files: `frontend/src/pages/configurations/`, `app/api/v1/routes/data_sources.py`, `voicebundles.py`, `integrations.py`, `telephony.py`, `settings.py`, `cron_jobs.py`, `app/services/cron/job_dispatch.py`.

These pages are not on the per-call hot path. They break when catalogs get large, and a few of them can pin an API pod by pulling a big object through it. Cron can dump a lot of work onto the eval pool at once.

### Cloud Storage

Browse calls `browseS3` with `maxKeys = 1000`, then sorts in the browser. There is no continuation token. A bucket of recordings for 1 million calls hides everything past 1,000 and, on failure, looks empty (errors are handled for upload and delete, not for browse).

Upload and download of data-source objects read the whole body through the API (`await file.read()`, then the download returns the object body).

**Change.** Page with the provider's cursor. Show a browse error. Presign upload and download. Playback stays on a presigned URL.

**Controls.** Path breadcrumb, upload, delete, download, sort. Sort and filter belong on the page you fetched only if the page is complete. With a cursor, sort has to be server-side or clearly "this page only".

### VoiceBundle

Opening the page loops about **23 providers** and awaits a model-catalog call for each, cached 5 minutes, plus every bundle, AI provider, and integration. A provider outage fails that slot silently. Query keys are not scoped by workspace. The editor, the `?edit=` deep link, and three credential pickers live in one 1,750 line component.

**Change.** One catalog endpoint, or fetch options for the provider the user picks. Split the form from the list.

**Controls.** Create, edit, provider dropdowns, credential pickers. The dropdown is the expensive control. Everything else is a single-row write.

### Integrations

On mount: all integrations, all AI providers, telephony configs, and LLM gateway settings. Admin gating exists. Secrets are write-only password fields, and the copy says the browser does not display them. `getIntegrationApiKey` still returns a plaintext key and has no caller today. A later "reveal" button, or any XSS, can call it. VoiceBundle and Integrations use different query keys (`aiproviders` vs `ai-providers`) for the same list, so the cache does not dedupe.

**Change.** Delete or tightly role-gate the plaintext key method. One query-key factory per resource. Split voice, LLM, and telephony forms (the file is about 2,050 lines).

**Controls.** Connect, disconnect, save credentials. Single-row. The risk is the secret-read API, not the button.

### Telephony numbers

`listTelephonyNumbers()` has no paging. The page also loads every dial target and the outbound pool, then filters by provider in the browser. The derived "active numbers" array is rebuilt every render.

**Change.** Page by provider. Memoize the derived lists. This inventory is also what the outbound pool in section 7 admits calls against; a truncated list and a pool of 5 are separate bugs that show up in the same screen.

**Controls.** Add number, release, provider filter, outbound pool display. Filter server-side. The pool display should show the leased count from Redis, not a full refetch of every number.

### API keys

The product cap is 5 keys, so the list size is fine. The new secret is held in React state until the modal closes. There is no error state and no reader gate. A failed list looks empty.

**Change.** Show the secret once, drop it from state on dismiss, show errors. The serious issue is the login key in `localStorage` (section 15), not this page's length.

**Controls.** Create, revoke, copy. Fine at a cap of 5. If the cap is raised for automation, page the list then.

### Cron jobs

On mount the form downloads all cron jobs, all evaluators, all agents (100 cap), all personas (100 cap), and all scenarios (100 cap). None of the query keys include the workspace. Picking an evaluator past the cap is impossible, and a workspace switch can show another workspace's jobs until the slower request finishes.

The dispatcher is a single flight (Redis lock), then enqueues **every** due job on that tick with no awareness of the 128 eval slots. Many orgs firing at the same minute land on the same pool as import judging.

**Change.** Search evaluators by name. Include the workspace in the key. Enqueue cron runs through the fair dispatcher and cap how many jobs a tick may release.

**Controls.** Create, enable/disable, schedule picker, "run now". Run-now must take a slot, not jump the queue. The agent/persona/scenario dropdowns are the silent-truncation bug again.

### Knowledge bases (reached from Tools)

Not in the top-level sidebar, but ingest is part of this configuration surface. Ingest loads the file, all chunks, embeds in batches of 32, and inserts vectors **one row at a time**. Retrieval is pgvector IVFFlat with `lists = 100`, which is the wrong index shape once chunks pass a few hundred thousand, and the filter is not applied before the vector scan. Upload is multipart through the API.

**Change.** Presign the upload, multi-row insert, HNSW or a tuned index, pre-filter document ids. This matters because an agent tool call during a million-call eval will add this latency to every call that uses a knowledge base.

### Keep

Write-only secret fields. Admin gating on integrations. A product cap on API keys. Cron's single-flight lock (keep it, and add the slot cap in front of the enqueue).

---

## 15. IAM, profile, login, and platform admin

Files: `frontend/src/pages/iam/IAM.tsx`, `profile/Profile.tsx`, `auth/`, `platform/`, `frontend/src/lib/api.ts`, `frontend/src/store/authStore.ts`, `platformAdminStore.ts`, `frontend/src/components/Layout.tsx`, `WorkspaceSwitcher.tsx`.

### Login and session

Password login is in good shape. Access and refresh tokens stay in memory. Cookie sessions are on by default. CSRF is sent on writes. Refresh is single-flight. A disabled org is sent back to login with a message. Logout clears the session. OIDC keeps PKCE state in `sessionStorage`.

The API key path is not. `authStore` reads and writes `apiKey` in `localStorage`, and the Axios interceptor sends it as `X-API-Key` when cookie sessions are off. Any script that runs on the origin can take a long-lived key.

On refresh failure the client clears the session and hard-redirects to `/login`. It does not cancel in-flight queries, so they can 401 in a burst and stampede the refresh. Refresh failure also does not distinguish "this workspace is gone" from "this session is dead".

Profile, on password change, clears the entire React Query cache, logs out, and redirects. That is correct, and it is why the cache must not hold secrets.

### App shell (every page)

`App.tsx` statically imports every page. There is no `React.lazy`. The production bundle is **one JavaScript file of about 5.5 MB** (built artifact `frontend/dist/assets/index-*.js`), plus about 376 KB of CSS. `dist` is about 17 MB because `public/` still contains persona photos of 1.3–1.6 MB and screenshots that nothing in the source references. Every login downloads LiveKit, Pipecat, ElevenLabs, Vapi, Retell, React Flow, and the chart library before Dashboard can paint.

`frontend/src/lib/api.ts` is **7,066 lines** and `types/api.ts` is **2,795**. List methods return `Promise<any>`. Nothing passes an `AbortSignal`. Navigating away does not cancel the request. There are about **746** uses of `any` under `frontend/src`. Lint does not ban it. There are 17 test files, almost all pure helpers. There is no test around the workspace switch or the auth interceptor.

React Query defaults are `retry: 1` and no refetch on window focus, which is good, and `staleTime: 0`, which means every mount refetches. About **52** `refetchInterval` sites across 31 files. Six of them are fixed intervals even when the job is idle (called out in the sections above).

**The workspace bug.** The active workspace id lives in Zustand and in `localStorage`. An interceptor stamps `X-Workspace-Id` at send time. Most query keys do **not** include the workspace id. Switching workspace calls `invalidateQueries()` with no filter. A slow response from workspace A can land in the cache after the user is looking at workspace B, because the key is just `['agents']` or `['alerts']`. Layout, Alerts, Cron, VoiceBundle, and Studio all share this shape. Metrics Management and the call-import queries already include the workspace. That is the pattern.

Layout loads `listAgents` with the default **100** for the global agent dropdown and renders every row with no search. Past 100 agents the shell cannot select the rest, and every page pays for that list on mount. Agent-dropdown and sidebar state live in `Layout`, which also renders the page, so opening the menu re-renders whatever page is open, including the 4,500 line metrics screen. The mobile sidebar and the desktop sidebar are both mounted; each includes the workspace switcher, and the effect can invalidate the whole cache twice on first load.

`OrgSwitcher` exists and is never mounted. Multi-org users change org from Profile, which lists every org with no search.

Nav highlight is exact-match except for Tools and Metrics. `/alerts/:id` does not keep Alerts highlighted. Enterprise items stay in the sidebar even when the license will swap in an upgrade page after the click.

There is no `dangerouslySetInnerHTML`. Markdown is rendered without raw HTML. Keep it that way. The only frontend env var is the API URL.

### IAM

The member table is the entire organisation, with loading and empty states and no error state. A 403 looks like an empty org. Password reset holds the new password in component state and can reveal it. That is acceptable for an admin reset if it is not logged, cached, or toasted. The file is about 1,030 lines; workspace members and roles are already separate components.

### Platform admin

The platform token is in `localStorage`, and `Authorization: Bearer` is read back from there. The org table requests `limit: 200` and ignores the API's `offset` and `search`. Members load the full user list. An admin can set a password in the modal. Orgs and signup codes use `useEffect` plus `useState`, not React Query, so they have no shared cancellation or retry. The page is outside the normal auth route and redirects in an effect.

An XSS on the origin takes a cross-tenant admin bearer. A platform operator with more than 200 tenants cannot find an org.

### What has to change

**Critical. Put `workspaceId` (and org id) in every tenant query key, and pass `AbortSignal` into Axios.** Invalidate with a predicate, not a blanket wipe, except on logout and password change. This is the bug that makes every other page unsafe to use while switching workspaces under load. Do it once, in the query layer, not page by page after each incident.

**High. Split the bundle.** `React.lazy` per route. Charts, the flow editor, and the voice SDKs in their own chunks. The login page should not download the voice stack. Delete the unreferenced public images.

**High. Stop storing long-lived secrets in `localStorage`.** Cookie session for the product API key and for the platform admin, same as the password session. Until that ships, assume any XSS is a full compromise.

**High. The global agent switcher is a typeahead**, against a paginated search. It is not a 100 row prefetch on every page.

**High. Platform org list uses the API's search and offset.** Page members. Move those reads onto React Query so a 401 and a cancelled navigation behave like the rest of the app.

**Medium. Show `isError` on every list** that today treats failure as empty: Dashboard, alerts, IAM, API keys, S3 browse, metrics seed. The metrics seed must run only after a successful empty response, once per workspace.

**Medium. One sidebar instance.** Prefix-match nested routes. Hide or badge license-gated items.

**Medium. Split `api.ts` by domain**, or generate the client from the API schema. New endpoints should not keep landing in a 7,000 line file with `any` returns. Ban new `any` on the client. Add tests for the query key and the 401 refresh interceptor. Those two are the tenancy and auth contracts.

**Low. Cancel in-flight queries when refresh fails**, so a dead session does not fan out into a 401 storm.

**Low. Mount the org switcher** in the header once orgs are numerous, with search.

### Controls that show up on every page

- **Workspace switcher.** Navigates off detail routes before invalidating. Keep that. Fix the cache key so the invalidation is not racing a stale response.
- **Org switch (profile).** Full cache clear is right because the session context changed. Show an error if the profile request failed; a blank form looks editable.
- **Global agent dropdown.** The single most repeated "loads too much, then stops" control in the product. Search, don't prefetch.
- **Sidebar links.** Cheap. Fix the active state so deep links still show where you are.
- **Logout.** Clears the session. Also clear the platform token and the API key. Confirm both stores are covered; the password path is, the platform path must be too.

### Keep

Cookie session, CSRF, in-memory refresh, single-flight refresh, no bearer token written for password login, no raw HTML injection, enterprise route gate, OSS quota checks on create, and the comment in `useRole` that the API is the real authority. The UI hiding a button is not the security boundary. Hiding it is still worth doing so the product matches the role.

---

## 16. Patterns we are following, and the ones that are missing

This is the same list a design review would use. It is here so a fix in one section does not invent a second pattern.

**Already in the codebase, and worth keeping:**

- Bulkheads by queue (partial: six import-related queues still share one worker).
- Fair-share leases for import and eval (workspace, org, global, per job).
- Delayed, aggregated usage flush.
- Slice sharding with a catalog registry and a Redis epoch so processes drop a stale map.
- A separate media process and a short "place the call, return" task for telephony.
- Idempotency-Key on platform-import create.
- Presigned URL support on the blob backends (the hot path often ignores it).
- Cursor listing for traces (the calls hub does not use it).
- 202 plus an object write-ahead log for trace ingest.
- Liveness separated from readiness.

**Missing, and called out in the sections above:**

| Pattern | Where it hurts |
| --- | --- |
| Backpressure at enqueue | Trace ingest returns 202 with no queue check. Simulation create always `.delay()`. HTTP rate limits skip the bulk APIs. Leases fail open |
| Leases and a reconciler | Simulations stick in `RUNNING`. Import slot integers leak. Trace idle-close re-queues the same 200 |
| Idempotency | Simulation create, carrier webhooks, Vobiz answer, outbound retry |
| Per-tenant and per-provider bulkheads | Harbor, voice eval, LLM, STT. Imports have the tenant half only |
| Circuit breakers | All external providers |
| Thin catalog, fat data elsewhere | Call JSON, trial transcripts, and scores are still written to the catalog |
| Keyset pagination and rollups | Calls list, import aggregate, alerts, results overview, usage breakdown |
| Outbox between catalog and shards | Rebalance copies, commits, then deletes. A failed epoch publish can delete the only copy. Not on the daily hot path, but it is how you will move data when a shard fills up |
| One migration runner | Every pod migrates itself |
| Connection budget | Pools are per process with no global ceiling |
| CQRS for read-heavy product surfaces | ClickHouse is only the trace store. Eval charts and alerts still scan the OLTP rows |

Sharding does not fix the items in that table. It spreads stored bytes. It does not add fair scheduling, and the catalog remains the hotspot for auth, run rows, and the JSON we still dual-write.

---

## 17. Where to start the discussion

These are themes, not a sprint plan. The order is "what makes the other work possible".

**First, so that more replicas are safe.**

- Postgres connection budget and PgBouncer.
- Migrations as one locked Job.
- Redis split and durable.
- Object storage instead of `./uploads` and `./.data`.
- Workspace id on every query key, and no long-lived token in `localStorage`.
- Replace 6 digit ids (calls, simulation runs, evaluator results) before the space fills. This one gets worse by itself, even if traffic does not grow.

**Second, so that 1 million a day is a capacity conversation instead of an architecture one.**

- Trace ingest: higher org budget, no parse on the API, 429 when the queue is deep, incremental derive, idle-close that marks rows claimed, TTL, no `FINAL` on the hot path.
- Simulations: one leased trial per queue item, a stuck-run sweeper, no database connection held for the whole conversation, an LLM rate limit.
- Voice: calls on the media tier, not inside a Celery child, atomic per-org and per-provider caps.
- Imports: stream audio, lease slots that fail closed, a larger download pool split from the judge pool, rollups for charts, Flexprice off the hot path, presigned upload.
- Webhooks: verify, dedup, return 200, download in a worker.
- Alerts and the calls list read rollups, with the missing time indexes.

**Third, so the team can keep shipping once the above is in place.**

- Route-level code splitting and a smaller `api.ts`.
- Break up the largest screens: import evaluation detail (~10,400 lines), import detail (~5,300), metrics management (~4,500), prompt partials (~2,800), integrations (~2,050).
- Server search instead of silent caps at 100, 500, and 1,000.
- Poll only while work is in progress; prefer the SSE that traces already have.
- Error states that are not blank pages.
- Tests for tenancy and session refresh.

A load test belongs next to the second group, not before the first. Useful scenarios: trace export at a few hundred requests per second, the calls list with one live call and many open browsers, a CSV import of a few hundred thousand rows, and a simulation run of a few thousand trials with two organisations at once. The numbers in this document are ceilings from the code. The test will show which ceiling you hit first on the real cluster.

---

# Part B — Code shape and low-level design

Part A says where the product runs out of room. This part says whether the code itself is doing unnecessary work, and whether the next feature has a place to go. Adding pods does not fix either. A request that does three database round trips still does three round trips on every pod. A 10,000 line screen still has to be understood by the next person who adds a button.

## B1. The rule for this codebase

**One user action, one purpose, one cheap round trip.** A list must not load a blob. A read must not write. A poll must not repeat a heavy query. A second request is allowed only when the screen shows a second thing the user asked for.

**A file that grows past a few hundred lines is a failed split, not a badge.** Routes stay thin. A use-case function does one job. A query function returns one shape. A React page composes panels. A panel does not fetch the world.

**New work extends a seam. It does not edit the giant function.** A new voice provider, a new metric type, a new import source, or a new chart is a new module that plugs into an existing interface. If the only way to add it is to scroll a 4,000 line file, the design is already wrong.

The house style, in one picture:

```text
Browser panel  →  feature hook (query key includes workspace)
                →  feature API module (one function, AbortSignal)
                →  route (auth, parse, status code)
                →  use-case service (the business rule)
                →  query module (one SQL or one ClickHouse statement)
                →  worker, only when the work is slow
```

Today the middle is often missing. The route holds the SQL, and the page holds the queries, the filters, and the markup.

## B2. What is already modular

This is not a junk repository with no structure. The folders are the right idea, and several seams are real. New code should extend these, not walk around them.

- Backend is split into `app/api` (HTTP), `app/services` (use cases), `app/workers` (slow work), `app/db_sharding` (where a row lives), `app/core` (auth, limits, middleware), `app/models` (tables and DTOs).
- Speech-to-text clients live as one file per provider under `app/services/ai/stt_clients/`. That is a strategy: a new provider is a new file.
- Blob storage has more than one backend, and presign already exists as a method.
- Import and eval dispatch is its own package (`app/workers/concurrency/`) with caps per workspace, org, and job. That is the scheduling policy, and it is not buried in a route.
- Telephony already separates "place the call" from "hold the socket".
- The frontend is split by product area under `frontend/src/pages/`, and Imports already has a `components/` folder (upload modals, mapping, transcript, progress). Shared widgets live in `frontend/src/components/`. Pure helpers in `frontend/src/lib/` have the only real tests.
- Call-import and metrics screens already put the workspace id in the React Query key. That is the tenancy seam. Copy it. Do not invent a second one.

The failure is that the **hot features outgrew the seam**. The next thousand lines went into the route and the page, because that was faster than opening a new file. That is the habit to stop.

## B3. Cross-cutting code problems

These show up in almost every section. They are listed once so the per-section notes can stay short.

**Routes are doing the job of services.** `app/api/v1/routes/` is about 51,000 lines. `call_import_evaluations.py` is **9,937 lines, 44 endpoints, and about 80 direct `db.query` calls**. `call_imports.py` is 4,645 lines and about 31 queries. `agents.py` is 1,843 lines and about 40 queries. `playground.py` is 2,202 lines and about 43 queries. `voice_playground.py` is 2,549 lines and about 39 queries. A route function should be: authenticate, validate the body, call one service, map the result to a status code. SQL inside the route cannot be reused by a worker, cannot be tested without HTTP, and gets copied into the next endpoint.

**Two god modules sit under every feature.** `app/models/database.py` is **3,737 lines** of every table. `app/models/schemas.py` is **6,372 lines** of every request and response. Adding a field to a call means opening a file that also owns personas, billing, and alerts. Split by domain: `models/calls.py`, `schemas/calls.py`, and the same for imports, sims, traces, identity. The tables can stay one database. The source files should not.

**The judge is one 3,570 line module.** `app/workers/tasks/helpers/llm_evaluation.py` builds prompts, parses answers, and special-cases model families (Jev, Together) in one file. A new metric type means editing the middle of that file. The prompt builder, the parser, and each model dialect should be separate, with one interface: `score(transcript, metrics) -> scores`.

**The frontend client is the same mistake.** `frontend/src/lib/api.ts` is **7,066 lines**. Every screen imports `apiClient` from it. There is no per-feature module, no generated types, and list methods return `any`. A change to the imports client is a change to the file that also does login. Split by domain, and pass `AbortSignal` so leaving a page cancels the request.

**Pages fetch inside render trees that are too big to reason about.** The largest screens:

| File | Lines | What it should become |
| --- | ---: | --- |
| `CallImportEvaluationDetail.tsx` | 10,368 | One shell, plus a tab component per view (rows, chart, insights, export) |
| `api.ts` | 7,066 | One module per product area |
| `CallImportDetail.tsx` | 5,331 | Shell, row table, upload, mapping |
| `MetricsManagement.tsx` | 4,518 | List page, and one component per dialog |
| `schemas.py` | 6,372 | One schema module per area |
| `call_import_evaluations.py` | 9,937 | Thin routes plus one service per use case |
| `database.py` | 3,737 | One model module per area |
| `llm_evaluation.py` | 3,570 | Prompt, parser, and one dialect per model family |
| `PromptPartials.tsx` | 2,813 | List and editor |
| `Integrations.tsx` | 2,055 | One form per provider family |

A practical limit: **a new file past ~400 lines needs a reason, and a file past ~800 lines is a split before the next feature.** Do not boil the ocean in one change. The rule applies to the next edit: when you touch the file, extract the piece you are changing.

**The same concept has two names.** Integrations uses the query key `['ai-providers']`. VoiceBundle uses `['aiproviders']` for the same list. Two caches, two requests, two places to forget the workspace id. One key factory per resource: `keys.integrations.list(workspaceId)`.

**Reads that write, and lists that compute.** API-key auth updates `last_used` on the request path. Simulation progress reloads every transcript to increment a counter. The calls page runs several `COUNT`s and then loads the rows. The visualizations tab loads every score document to draw a chart. Each of these is an extra round trip that a counter or a rollup would remove. Command and query are mixed: the screen asks a question and the server changes state or scans a table to answer it.

**Work is done twice because two layers do not trust each other.** Trace bodies are parsed on the API and again in the worker. Recordings are downloaded, stored, then downloaded again for transcription and sometimes a third time to measure duration. Trial JSON is written to the catalog and again to the shard. The UI polls a resource that an SSE stream is already pushing. Deduplicate at the boundary. One owner for each fact.

**There is no repository, and that is fine if the query functions are real.** Do not introduce a generic repository class. Do extract `list_calls(workspace, cursor, filters)` into a module the route and the alert job both call. Today the alert job and the calls page each have their own scan.

**Tests protect helpers, not behaviour.** Frontend tests are almost all pure functions (17 files). The workspace switch, the query keys, and the 401 refresh have no test. Backend use cases that live inside route functions are only testable through HTTP. Extract the use case, then test the use case. A 9,000 line route will not grow a useful test suite.

**What "done" looks like for a new feature.** A short checklist, so reviewers can say no without a debate:

1. The route file did not gain SQL or a new 200 line function.
2. The use case has a name and a test that does not boot the whole app.
3. The list endpoint returns ids and summaries, not transcripts or `call_data`.
4. The React Query key includes workspace id. The request takes an `AbortSignal`.
5. The screen does not poll unless something on it is in progress.
6. The new UI lives in a new component. The page file did not grow by hundreds of lines.
7. A new provider or metric type is a new class or file behind the existing interface.

## B4. Per section

Same sidebar order as Part A. Each note is the code, not the cluster.

### Dashboard

The page is small, which is the right size. The bug is what it asks for. `getDashboardSummary` is a catalog count, and the carousel then fetches the full TTS catalog on the home page, on every visit, for a widget the user did not request. That is a second request with no user action behind it.

**Shape.** Keep `Dashboard.tsx` as composition: summary, quick-start, nothing else. The carousel is a separate lazy component, or it is deleted from this route. The summary endpoint stays one query against counters. It must not grow into "also load recent calls" inside the same handler. Recent calls are a different use case.

**Next feature.** A new home-page card is a new endpoint that reads a counter, plus a new small component. It is not another query stuffed into `dashboard.py` and another fetch in the page.

### Metrics

`MetricsManagement.tsx` (4,518 lines) is the list, the create flow, the classification editor, categories, AI generate, and partial import. `metrics.py` is 2,555 lines and about 24 direct queries. Studio source pickers each fire their own list (`call imports`, `rows`, `recordings`, `calls`, `evaluator results`) capped at 100, so opening Studio is five requests that all return the wrong page of a large account.

**Wasted work.** Search filters in the browser, so every keystroke re-renders the whole 4,500 line tree over the full metric array. The empty-list effect seeds default metrics, which is a write triggered by a read, including a failed read.

**Shape.** One hook, `useMetrics(workspaceId, filter)`, that calls a paged endpoint. One component per dialog. The seed belongs in a migration or an explicit "load defaults" button, never in a `useEffect` on an empty array. Scope pickers are a shared `EntitySelect` with server search, used by metrics, cron, and alerts. Do not copy the 500-row fetch into a fourth screen.

**Pattern.** Metric types (score, classification, and the next one you add) should be a strategy behind `build prompt` / `parse answer`, not more branches in `llm_evaluation.py`. The editor and the judge must share that strategy so the UI cannot configure a shape the judge cannot score in one call.

### Simulations — Agents, Personas, Scenarios, Tools, runs

Agent, persona, and scenario routes are each over 1,500 lines (`agents.py` 1,843 with about 40 queries, `personas.py` 1,525 with about 32). The pages call `listX()` with a default of 100 and filter on the client. The shell does it again for the global agent dropdown. Opening any page therefore pays for an agent list the page may not show, and the list is a different cache entry from the page's own list when the keys differ.

**Wasted work on a run.** The worker reloads every trial payload every 5 seconds to update two integers. The open run page refetches the run and every trial every 4 seconds. One trial finishing causes a full reread on the server and a full reread in every open browser. The counter belongs on the run row. The page polls `{status, completed, failed}`. The matrix asks for one page of cells. The drawer asks for one transcript when it opens.

**Shape.** `simulation_runs.py` should become: create, cancel, get progress, list trials, get trial. The Harbor subprocess stays the trial runner. Progress accounting is a few lines in the trial-finish path, not a loop in the parent. `NewSimulationRunModal` should not own four catalog fetches. It receives search callbacks.

**Pattern.** A run is an aggregate: one parent, many trials. The code treats the parent task as the aggregate and keeps the trials inside it. Invert that. The parent is a row. The trial is the unit of work. That is both the scale fix from Part A and the design fix: you can test one trial without standing up a 6 hour job.

**Next feature.** A new column on the run matrix is a field on the trial summary DTO. It is not a reason to load `call_data` into the list.

### Playground and live voice

`playground.py` (2,202 lines, ~43 queries) and `voice_playground.py` (2,549 lines, ~39 queries) are products living inside route files. Provider differences (Vapi in the browser, Retell and ElevenLabs created on the server, then a sleep-loop poll) are branches in the route. The poll holds a database session and the decrypted key. That is a use case (`watch_call`) pretending to be a request.

**Wasted work.** While one call is in progress, the playground refetches the entire result list and the entire recording list. Pagination slices the array after the download. The voice page adds more intervals, including ones that run when nothing is in progress.

**Shape.** One `PlaygroundCallService` with `start`, `status`, `stop`. Provider-specific start is a strategy object (`VapiBrowserCall`, `RetellServerCall`, `ElevenLabsServerCall`) so the next provider is a file, not a new branch in a 2,000 line route. Status comes from a webhook or a single-id poll. The screen subscribes to the ids it started, not to the whole history.

**Pattern to copy.** Telephony's `initiate` task plus media process plus Redis session is already the strategy's skeleton. The playground and the voice evaluator bridge should call that skeleton. They should not grow a third copy of "how a call lives".

### Evaluations

Suite start does insert, commit, id probe, and enqueue **per trial inside the HTTP request**. That is N round trips for one click, and the id probe is the 6 digit collision check. Bulk insert, one dispatcher message.

The results page downloads 500 full `metric_scores` documents and then drops most of the points on the floor to draw a trend. The chart's data shape is a bucket (`day, pass rate, count`). Returning the full document is the wrong DTO for that widget. List DTO and chart DTO are different types. They should not share a "give me the row" function.

**Shape.** `evaluator_run_service.py` is the right place and should be the only place that creates runs. Routes in `evaluators.py` (~24 queries) and `evaluator_results.py` (~32 queries) shrink to call it. Judge alignment's serial loop becomes "enqueue N samples through the same dispatcher", not a private loop with its own session lifetime.

### Imports

This is the sharpest LLD problem in the repo, because the feature is also the largest.

`call_import_evaluations.py` at 9,937 lines is not a module. It is forty-four handlers and the SQL for charts, exports, retries, and row detail. `call_imports.py` at 4,645 lines repeats the pattern for the import itself. `bulk_ops.py` (2,353) and `scatter_gather.py` (1,744) are real extractions, which proves the split works. The next extraction just did not happen. `call_import_evaluation_pdf_report.py` (2,945 lines) and `call_import_metric_clusters.py` (1,455) are further use cases that still reach around the route.

On the frontend, `components/` already exists (upload, mapping, transcript, progress, side panel). The page files did not become shells. `CallImportEvaluationDetail.tsx` is still 10,368 lines and `CallImportDetail.tsx` is still 5,331. Extraction started and then stopped. Finish it: the page chooses the tab and passes ids. The tab owns its query.

**Wasted work, per click or per poll.**

- Upload reads the file into the API, writes S3, then a worker reads it all back to parse.
- One recording is downloaded up to three times (fetch, transcribe, duration probe).
- Visualizations polls a handler that loads every score row, every 5 seconds, while a run is open.
- "Select all" and retry build a Python list of every id.
- Opening a row can request up to 5,000 full bodies even though the table shows 100.
- Flexprice HTTP sits in the row-finished function, so billing latency is part of scoring.

**Shape, use case by use case.** Each of these is its own module with its own input and output. None of them import the route file.

| Use case | Owns | Must not do |
| --- | --- | --- |
| Stage upload | Accept an object key, parse in batches | Read the HTTP body into a `bytes` |
| Dispatch | Claim the next row id | Load the transcript |
| Fetch audio | Stream to object storage, store duration | Hold the file in a `bytes` and return it |
| Judge | Scores in, scores out | Call Flexprice or download audio |
| Chart | Read the rollup | `query.all()` of `metric_scores` |
| Insights | A sample of ids, then those transcripts | Load every pair, then sample |
| Export | Page through rows, write parts | One gzip of the whole run |

**Pattern.** The pipeline is a state machine on the row (`pending → fetched → transcribed → scored`). Each state has one worker function. Adding a step (for example, redaction) is a new state and a new function, registered in the dispatcher. It is not a new block pasted into `evaluate_call_import_row_core.py` (already 1,107 lines) and a new tab pasted into the 10,000 line screen.

**Frontend rule for this area.** A new button on the evaluation page is a new component file and a new hook. The pull request that adds it should show `CallImportEvaluationDetail.tsx` getting smaller or staying the same length. If the page file grows, the button was added in the wrong place.

### Prompts

`PromptPartials.tsx` is 2,813 lines for a catalog and an editor. `prompt_partials.py` is 981 lines and about 15 queries. The product is simple. The file size is the defect. Split list and editor. The optimization job is already a worker with a budget (`max_metric_calls`). Keep that function small. Do not let it grow a private copy of the judge. It should call the same `score(...)` interface as imports, on a sample.

### Observability and live traces

The pipeline modules exist (`ingest_pipeline`, `trace_service` at 1,988 lines, `otlp_mapper` at 1,496, ClickHouse store). That split is right. The waste is inside the steps:

- The route parses the body the worker will parse again. The route's job is auth, size check, and handoff.
- Derive reloads every span to recompute turns. Turn state should be updated from the new batch only.
- The calls hub (`calls_hub.py`) merges two stores in the API process and counts them on every page view. Listing and counting are two queries with two DTOs. The list DTO does not include `turns`.
- Call detail and the audio proxy put the blob on the same endpoint as the metadata. Metadata, transcript page, and audio URL are three use cases. The panel currently polls the fat one and also opens an SSE.
- `observability.py` is 900 lines and about 17 queries. Webhook handlers still do provider calls and file downloads inline. A webhook function is: verify, dedup, enqueue, return. The download is the worker you already have (`finalize_telephony_recording`).

**Pattern.** Ingest is a pipeline of pure steps: `accept → store raw → parse → append spans → fold header`. Each step has a function and a test with a fixture payload. `trace_service.py` at almost 2,000 lines is the next file to split along those step names, before the next trace feature lands in it.

**Frontend.** `Observability.tsx` charting 500 evaluator results in the browser is a DTO error: the overview asked for rows when it wanted aggregates. `SyntheticCallTracePanel.tsx` (about 1,020 lines) polling every span is the same error. The spans tab requests a page of spans. The header tab requests the header.

### Usage and billing

`org_usage.py` is 1,717 lines for what should be a few read models. `llm_usage.py` (1,547) already has the right write path: increment a counter, flush later. `flexprice_service.py` (1,386) is called from the judge. That is a layering violation. The judge finishes a row. A billing subscriber reacts. The judge does not import the billing client.

The Usage page refetches summary, breakdown, and the option catalog on every filter change and on window focus, then filters the options again in the client. Focus refetch is a request the user did not make. The breakdown DTO is already truncated at 100 and the client regroups it, which means the server returned the wrong grain.

**Shape.** `UsageQuery` with `summary`, `breakdown(group, cursor)`, `suggest(field, text)`. The page holds filter state and renders the result. It does not re-aggregate.

### Alerting

`alerts.py` is 661 lines and about 21 queries. `alert_evaluation_service.py` is 1,117 lines and pulls every call JSON in the window into Python. The rule ("is the failure rate over the threshold") is a few lines. The scan is the rest. The rule should call the same rollup query the calls overview uses. If both screens have their own scan, they will drift, and you pay for both.

The page loads every alert and filters in memory, and Evaluate-all is one request per rule from the browser. One request: `POST /alerts/evaluate?filter=...`. The server fans out.

**Shape.** Alert rule, alert evaluation, and notification delivery are three modules. `send_alert_notifications` already exists as a task. Keep the rule evaluator from knowing about PagerDuty. It emits "rule X fired". The notifier decides the channel.

### Configurations

Each settings page loads full catalogs on mount, and several load the same catalog under different cache keys. VoiceBundle's loop of ~23 model-catalog requests is the clearest waste: one screen, 23 serial calls, most of them for providers the user will not open. One `GET /model-options?provider=` when the dropdown opens.

`data_sources.py` streaming a whole object through the route is the route doing storage's job. The route returns a presigned URL. The browser talks to object storage.

Cron's form fetches jobs, evaluators, agents, personas, and scenarios up front. Four of those are the silent 100-cap lists again. The form needs a typeahead, which is the shared `EntitySelect` from Metrics. Cron dispatch should call the eval dispatcher. It should not have its own "enqueue everything that is due" path that bypasses the slot cap. Two enqueue paths means two places that forget fairness.

Knowledge-base ingest inserts vectors one row at a time after building the full chunk list. The use case is `ingest(document) -> chunks in batches`. The retrieval query is a separate function with the index hint. Do not hide both in the route (`knowledge_bases.py`, 653 lines, ~12 queries).

### IAM, login, shell, platform admin

**Shell.** `Layout.tsx` fetches agents, renders the sidebar twice, and owns UI state that re-renders the current page. The layout's job is chrome. Data for the agent switcher lives in a hook used only by that control. `WalkthroughProvider` selecting a fresh object from the license store re-renders the whole tree on a quota refresh. Select the fields the walkthrough reads.

**API client and session.** `api.ts` handling login, refresh, workspace header, and every product call is why a billing change risks auth. Split `http.ts` (instance, CSRF, refresh, workspace header) from `features/*/api.ts`. The refresh interceptor is the one place that handles 401. Feature code does not.

**Query keys.** A single `queryKeys` module. No string arrays written at the call site. A review rule: a `useQuery` whose key does not contain `workspaceId` is a bug, except for the platform-admin and the logged-in user.

**IAM and platform admin.** `IAM.tsx` (~1,030 lines) mixes org members, invites, and password reset. The workspace sections are already separate components. Finish that for the org tab. Platform admin bypasses React Query with `useEffect`, so it does not get cancellation or the shared 401 behaviour. That is a second data layer. Use the same client.

**Tokens.** `localStorage` for the API key and the platform token is a design bug, not only a security bug. It creates a second session mechanism next to the cookie session. One session mechanism. Feature code never reads a token.

## B5. Design patterns — use these, skip the rest

You do not need a pattern catalog. These six cover the ways this product actually grows. Each one is already started somewhere. The work is to make it the default.

| Pattern | Use it for | Already exists | Stop doing this instead |
| --- | --- | --- | --- |
| Thin route + use case | Every new endpoint | `bulk_ops`, Harbor job runner, flexprice as a service (but called from the wrong place) | SQL and branching inside `routes/*.py` |
| Strategy | Voice providers, STT, TTS, metric dialects, import sources | `stt_clients/`, storage backends | `if provider ==` inside playground, judge, and webhooks |
| Pipeline / state machine | Import row, trace ingest, simulation trial | Row statuses, trace `open/closed`, run statuses | The next step pasted into a 1,000 line task |
| DTO per screen | Lists, charts, detail | List responses that omit `call_data` in some places | One "full row" response reused by a chart and a table |
| Feature module on the client | Each sidebar area | `pages/<area>/components` for imports | `api.ts` plus a page file of several thousand lines |
| Pub/sub for live UI | Traces, run progress, import progress | Live-transcript SSE, Redis progress counters | A 3 second poll of the heavy endpoint |

Patterns to **not** add, because they would be ceremony here: a generic repository base class, a dependency-injection framework, an event bus for every write, CQRS as a project-wide architecture. ClickHouse for traces is already the one place where the read model is separate. Copy that idea for charts and alerts as a rollup table. Do not rebuild the whole app around it.

SOLID, in the form that matters for this repo:

- **One reason to change.** `llm_evaluation.py` changes when the prompt changes, when a parser changes, and when a model vendor changes. That is three reasons. Split them.
- **Open for a new provider, closed for the call loop.** The loop lives once. The provider is a new file.
- **A page depends on a hook, not on 40 query calls.** The hook depends on a small API module, not on `api.ts`.
- **The judge does not depend on Flexprice.** Billing depends on "a row finished".
- **Routes do not depend on SQLAlchemy query details.** They depend on a function.

## B6. How to apply this without a rewrite

A big-bang split of the 10,000 line files will stall the product. The rule is on the next change:

1. Touch a giant file only to move the code you are modifying into a new module, then call it.
2. No new `db.query` in a route file. If you need a query, it goes in the use-case module you just extracted.
3. No new fetch in a page file over 800 lines. The fetch goes in a hook next to a new component.
4. No new poll of an endpoint that returns more than a status object.
5. A new provider or a new metric dialect is a new file that implements the existing function signature. The pull request shows that the old `if` chain was not extended.
6. Add a test on the extracted function. That is how the module stays a module.

Do this first, because every later feature lands here anyway:

- Extract chart, export, and retry out of `call_import_evaluations.py`, and split `CallImportEvaluationDetail.tsx` by tab.
- Split `llm_evaluation.py` into prompt, parse, and dialects before the next metric type.
- Split `api.ts` enough that imports, traces, and auth do not share a file. Add `queryKeys`.
- Make the judge emit a billing event instead of calling Flexprice.
- Make list and progress endpoints return summaries, and point the existing polls at them.

Infra scaling (Part A, section 17) still matters. It will not make this code cheaper to change, and it will faithfully multiply whatever extra query you leave in the request.

---

# Part C — Are we following the battle-tested patterns?

A pattern is a named way to keep one kind of change from ripping through the codebase. We do not need all 23 Gang-of-Four patterns. We need the ones that match how this product grows: new providers, new metric types, new import sources, more tenants, and more people editing the same files. Where a pattern does not match the product, adding it would create the junk we are trying to avoid. Those are called out at the end, so nobody adds them "for completeness".

Status words:

- **Following** — the seam exists and new code can use it without editing a giant file.
- **Partial** — the pattern exists in one area and is bypassed in the area that is growing.
- **Missing** — the failure mode of this pattern is already in the code. This is what breaks later, not a style nit.

## C1. Principles (the concepts). Patterns are how you enforce them.

| Concept | The rule | Status | Where we stand | What breaks if we leave it |
| --- | --- | --- | --- | --- |
| Single responsibility | A module changes for one reason | **Missing** on the hot files | `llm_evaluation.py` changes for prompts, parsers, and model vendors. `call_import_evaluations.py` changes for charts, export, retry, and row detail. `api.ts` changes for every feature | Two people cannot edit the same feature. A fix in charts breaks export |
| Open/closed | Add a provider or metric type by adding a file, not by editing the loop | **Partial** | Voice providers, STT clients, auth providers, and historical import adapters are open/closed. The judge, playground call start, and webhook handlers are closed only by editing them | The next provider is a week inside a 2,000 line route, and it regresses the previous one |
| Liskov | A subclass must be usable wherever the base is used | **Partial** | `BaseVoiceProvider` promises `create_web_call` for every platform. The live bridge then special-cases ElevenLabs and raises for the others | Callers learn the subclass anyway, so the base type is a lie. Swapping a provider throws at runtime |
| Interface segregation | Do not force a client to depend on methods it does not use | **Missing** on the voice base | `BaseVoiceProvider` is one interface with many abstract methods (web call, agent CRUD, and more). A TTS-only provider still has to pretend to be a full telephony API | Stub methods that raise. The next small provider copies the stubs |
| Dependency inversion | High-level code depends on an interface. The concrete client is plugged in at the edge | **Partial** | FastAPI `Depends` for auth. Protocols for tools, historical imports, and auth providers. The judge imports Flexprice. Routes construct queries. Pages import the god `apiClient` | You cannot test the use case without the vendor, the database, and HTTP |
| Separation of concerns | HTTP, business rule, query, and UI are different modules | **Partial** | Folders exist (`api`, `services`, `workers`, `pages`). The hot path ignores them: SQL lives in routes, data fetching lives in page files | Every layer reimplements the same rule slightly differently |
| DRY | One fact, one place | **Missing** in a few expensive places | AI provider list has two React Query keys. Trace body parsed twice. Audio downloaded up to three times. Catalog JSON written twice. Suite-create and import-create each invent an id | The copies drift. One path gets the fix, the other keeps the bug, and you pay the cost twice per request |
| Command–query separation | A read does not write. A question does not scan a table the writer should have summarized | **Missing** on several screens | Auth updates `last_used` on read. Metrics seed writes because a read returned empty. Charts and alerts compute by loading rows | Reads get slower as data grows, and a failed read inserts data |
| Law of Demeter | A screen asks one neighbour for what it needs. It does not reach through four objects | **Missing** on large pages | A page calls `apiClient` for catalogs it will not show, then filters the result. Layout fetches agents for every page | One screen triggers a fan-out of requests. Changing the agent API breaks unrelated pages |
| Tell, don't ask | The object that owns the state performs the transition | **Partial** | Import rows and runs have status strings. Many places set the string directly instead of `row.mark_fetched()` | Illegal transitions (scored → pending, running forever) are easy to write and hard to find |
| Fail closed | If the protection mechanism is down, refuse the work | **Missing** on the slot lease | Trace rate limit fails closed. Import and eval slot acquire returns success when Redis errors | An outage removes the only cap. Tenants stampede the provider |
| Program to an interface | The caller names the operation, not the vendor | **Partial** | `get_voice_provider(platform)`, `HistoricalProviderAdapter`, `ToolProvider`, `AuthProvider` | The playground and the judge still say the vendor's name in the branch |
| Composition over inheritance | Build behaviour by combining small objects | **Partial** | Middleware is composed. Voice providers use a deep abstract base instead of small capabilities composed together | The base class becomes a junk drawer. Every provider inherits methods it does not want |
| High cohesion, low coupling | A package's files are about one thing, and other packages talk to it through one door | **Partial** | `db_sharding` and `workers/concurrency` are cohesive. `routes/call_import_evaluations.py` is not. Frontend features all couple to `api.ts` | A change in billing can break login, because they share a file |
| YAGNI / KISS | Do not add a pattern that has no change behind it | **Following** in spirit, then violated by file size | We did not build a generic repository framework. We did let files grow to 10,000 lines, which is the opposite of simple | The "simple" file is now the most expensive place to change |
| Encapsulation | Callers cannot touch the internals | **Partial** | Services exist, then routes reach into `db.query` and the UI reaches into full row JSON | Every caller depends on column layout. A column rename is a product-wide change |

## C2. GRASP — who owns the work

These are the responsibility rules behind the patterns in C3–C7.

| Concept | Pattern that enforces it | Status | Evidence |
| --- | --- | --- | --- |
| Information expert | The module that holds the data does the calculation | **Missing** for counters | Trial progress is computed by reloading every transcript. Call success is computed by loading `call_data` in the alert worker. The row already has the facts. A counter on the parent should answer |
| Creator | The object that uses a thing is the one allowed to construct it | **Partial** | `get_voice_provider` creates providers. Routes and tasks also construct clients and sessions ad hoc |
| Controller | One use-case object receives the request | **Missing** on large routes | 44 endpoints in one file, each its own controller with its own SQL. There is no `EvaluateImport` or `GetCallChart` object |
| Polymorphism | A new type is a new class, dispatched by the interface | **Partial** | Voice, STT, auth, historical import. Not the judge, not call start, not webhooks |
| Pure fabrication | A service that is not a domain noun, invented to keep cohesion | **Following** where it exists | `fair_dispatch`, `bulk_ops`, `ingest_pipeline` are fabrications and they are the healthiest modules. The routes that did not get one are the problem |
| Indirection | A stable middle so the caller and the vendor can change separately | **Partial** | Provider registries. Missing between the judge and Flexprice, and between the page and `api.ts` |
| Protected variations | Wrap the thing that will change | **Partial** | Providers are wrapped. Metric dialects, chart queries, and list payloads are not. Those are exactly what the next quarter will change |

## C3. Creational patterns

| Pattern | What it is for | Status | Evidence | Breaks when |
| --- | --- | --- | --- | --- |
| Factory method / registry | Turn a string (`"vapi"`) into the right class without a chain of imports at the call site | **Following** | `VOICE_PROVIDERS` and `get_voice_provider` in `app/services/voice_providers/__init__.py`. `get_llm_provider_registry`. `ProviderRegistry` in `app/core/auth/providers.py`. `_SessionLocalFactory` | A new platform that bypasses the registry and is constructed at the call site. Review rule: if you `import VapiClient` outside the provider package, you skipped the factory |
| Abstract factory | A family of related objects created together (STT + TTS + LLM for one bundle) | **Partial** | A voice bundle is the family, but it is assembled with sequential lookups and per-provider catalog calls, not one factory that returns a consistent set | A bundle can mix incompatible pieces. The UI fires one request per family member |
| Builder | Build a complex object in steps, with a valid result at the end | **Missing** for prompts and runs | Evaluation prompts are concatenated in `llm_evaluation.py`. Simulation create validates inline | An invalid prompt or an invalid run is representable. The next metric option adds another string concat in the middle of the file. A `PromptBuilder` and a `RunSpec` that cannot be built half-finished fix this |
| Singleton | One shared instance per process | **Partial, and dangerous where accidental** | Settings are a process singleton, which is fine. In-memory telephony sessions and the outbound pool fall back to module-level dicts. Worker catalog caches are process-global dicts with no eviction | A second pod does not see the dict. The dict is a silent capacity leak. Real singletons in this system are Redis and Postgres, not Python globals |
| Prototype | Copy a fully built object instead of rebuilding it | **Not applicable** | We do not clone heavy graphs per request | Do not add it |
| Dependency injection | Pass collaborators in. Do not construct them inside the function | **Partial** | `Depends` for the current user and the DB session. Services then new up HTTP clients and open their own sessions | The function cannot be run in a test with a fake provider. Constructor injection on the use case, with FastAPI wiring it, is the version to standardise |

## C4. Structural patterns

| Pattern | What it is for | Status | Evidence | Breaks when |
| --- | --- | --- | --- | --- |
| Adapter | Make a third-party API look like ours | **Following** for historical import. **Missing** for live call start | `HistoricalProviderAdapter` plus `VapiHistoricalAdapter`, `RetellHistoricalAdapter`, `ElevenLabsHistoricalAdapter` | Live playground and webhooks speak each vendor's dialect in the route. A vendor change edits product code. New live providers should be adapters behind the same port the historical ones already use |
| Strategy | Swap an algorithm without editing the caller | **Following** for STT, storage, auth, historical pull. **Missing** for scoring dialects and call runtime | `stt_clients/` is one file per vendor. `TelephonyMergeStrategy` is an enum of strategies. Judge dialects are `if model` inside one module | Every new model family edits `llm_evaluation.py`. That file is already 3,570 lines. The next dialect will break an older one |
| Facade | One simple door in front of a subsystem | **Partial** | Blob storage is a door. `apiClient` is a facade that became the whole house (7,066 lines). Shard sessions are sometimes hidden, sometimes not | Callers depend on every subsystem. Split into one facade per area (`importsApi`, `tracesApi`), each small enough to read |
| Decorator | Add behaviour around an object without editing it | **Following** at the HTTP edge | Middleware stack in `app_factory.py`: CSRF, read-only role, usage context, security headers, trusted host. FastAPI dependencies decorate routes | Do not put business rules in middleware (the usage middleware and the double auth already lean that way). A decorator wraps a call. It does not replace the use case |
| Proxy | Stand in front of an expensive object and control access | **Partial, inverted** | Presigned URLs are the right proxy: the API authorises, object storage serves bytes. Several playback and download paths proxy the bytes through the API instead | The API becomes a file server. Memory and sockets scale with audio, not with decisions. The proxy should be the URL, not the process |
| Bridge | Separate the abstraction (a call, a score) from the implementation (which vendor) | **Partial** | `BaseVoiceProvider` is the abstraction. Implementations are the subclasses. The bridge collapses because the abstraction is too wide and some callers skip it | You cannot add a vendor without touching the call loop. Narrow the abstraction to the operations the loop actually needs (`start`, `stop`, `fetch_recording`) |
| Composite | Treat a group and a single item the same way | **Partial** | Metrics have parents and children, rendered ad hoc in the prompt builder. A simulation run is a group of trials, but the code treats the run as one task | A nested metric or a nested suite needs another special case. A composite `Metric` (`leaf` or `group`) with one `render` and one `parse` removes the special case |
| Flyweight | Share immutable data instead of copying it per row | **Missing** on hot payloads | Metric definitions, voice bundles, and provider config are re-read per row or per page instead of a short-lived cache keyed by id | At high row rates you repeat the same catalog read millions of times a day. Cache the immutable definition for the length of a job |
| Private class data / module boundary | Keep tables and DTOs from becoming a global namespace | **Missing** | `database.py` (3,737 lines) and `schemas.py` (6,372 lines) are one module for every area | Any model change conflicts with every other model change. Split by domain. This is the structural fix for coupling |

## C5. Behavioural patterns

| Pattern | What it is for | Status | Evidence | Breaks when |
| --- | --- | --- | --- | --- |
| Chain of responsibility | A request passes through handlers that each do one check | **Following** | The middleware chain. Also the import pipeline in spirit: fetch, then transcribe, then score | A new cross-cutting check (quota, audit) gets pasted into every route instead of one link in the chain. Add the link. Do not copy the check |
| State | An object behaves differently per status, and only legal moves exist | **Partial** | Runs (`QUEUED → PREPARING → RUNNING → …`), import rows, traces (`open` / `closed`) use status strings. Nothing owns the allowed edges. A dead worker leaves `RUNNING` because no state object times it out | Illegal writes, stuck states, and a sweeper that does not know the legal recovery move. One `transition(from, to)` per aggregate, with the timeout edge written down |
| Observer | When X changes, interested parties hear about it. The subject does not import them | **Partial** | `SutLatencyObserver`. Live transcript SSE is pub/sub. The judge calling Flexprice is the opposite of observer: the subject imports the listener | Billing, webhooks-out, and "refresh the chart" cannot be added without editing the judge. Emit "row finished". Subscribers do the rest |
| Pub/sub | Same idea, across processes | **Partial** | Redis for live turns and for progress counters. The UI still polls the heavy read | You pay for the stream and the poll. Subscribers should listen. The poll, if it stays, hits a generation counter |
| Strategy | Already in C4 | | | |
| Template method | The skeleton of an algorithm is fixed. Subclasses fill steps | **Following** on providers. **Missing** on jobs | `BaseVoiceProvider` defines the steps. Import processing is copy-and-edit across `process_call_import_row`, `transcribe_…`, `evaluate_…` rather than one skeleton with hooks | The next import-like pipeline (chat, platform, studio) copies the skeleton and forgets a step (lease release, billing, status). One `Pipeline.run()` with hooks |
| Command | Represent the work as an object: do, undo, log, retry | **Partial** | Celery tasks are commands. They are not idempotent, and cancel is not a first-class inverse. Create-run has no idempotency key | Retries double-charge or double-dial. A command carries a key and a `compensate()`. The task body checks the key before the side effect |
| Mediator | Widgets and services talk through one coordinator, not to each other | **Missing** on the big screens | `CallImportEvaluationDetail.tsx` knows about rows, charts, exports, insights, and polls. There is no page-level state machine those panels share | A new panel copies a poll and a fetch. A thin page mediator holds `{importId, tab, runStatus}` and panels subscribe |
| Iterator / cursor | Walk a large set one page at a time | **Partial** | S3 has a chunk iterator. Export reads 1,000 rows. Several callers then pass `part_rows=2**31` or `.all()` | Someone will call `.all()` on the next feature because the paged function is not the only door. The unpaged function should not exist for those tables |
| Memento, Visitor, Interpreter | Snapshot/restore, walk a tree with new operations, a little language | **Not applicable** | Metric JSON is not a language we should interpret with a new pattern. Prompt building is a builder, not an interpreter | Adding these now is junk. See C8 |

## C6. Patterns that keep a SaaS from breaking under its own features

These are the ones that fail in production even when the Gang-of-Four list is clean. They are still low-level design: they live in code, not in Kubernetes.

| Pattern | The rule in this repo | Status | What is already there | What breaks |
| --- | --- | --- | --- | --- |
| Service layer | One use-case function. The route only maps HTTP | **Partial** | `bulk_ops`, Harbor runner, alert service, flexprice service | Routes of 2,000–10,000 lines. Workers cannot reuse the rule. Tests need HTTP |
| Repository / query object | One function per query shape, shared by the screen and the job | **Missing** as a rule | Queries are inlined. `scatter_gather` is the closest thing to a shared query layer | Alerts and the calls page drift into two scans. A new filter is implemented twice |
| DTO per use | The list, the chart, and the detail are different types | **Partial** | Some list paths omit `call_data`. Schemas exist | Charts receive full score documents. Detail and poll share one fat response. The client throws fields away after paying to load them |
| Unit of work | One transaction for one business action. Commit at the end | **Partial** | A SQLAlchemy session is a unit of work. Suite create commits once per trial. Shard check-in runs extra SQL on every connection return | A request holds a transaction open across provider HTTP calls, or commits a half-finished suite. Commit once, after the in-memory work, never across a vendor call |
| Idempotency | The same request twice is the same result once | **Partial** | Platform-import create accepts `Idempotency-Key`. Simulation create, webhooks, and outbound dial do not | Double click and carrier retry duplicate runs and phone calls |
| Retry with a budget | Retry a known-safe step. Do not retry a side effect that already happened | **Partial** | Celery `max_retries` on tasks. Outbound task retries after it has already failed the call and released the slot | Duplicate dials, duplicate LLM spend, slots held by poison messages. Retry only the step that did not complete, with a key |
| Circuit breaker | After N failures against a vendor, stop calling them for a short window | **Missing** | Retries are per task. Nothing is shared across tasks or orgs | One vendor outage fills the worker pool for the whole task time limit. Every tenant waits |
| Bulkhead | A failure in one workload cannot occupy the workers of another | **Partial** | Separate queues for traces, usage, Harbor, audio. Imports, diarization, and eval share 12 threads. Voice calls share the audio queue | A big import delays cancel and scoring. A voice call blocks audio metrics |
| Backpressure | When the queue is deep, the door refuses new work | **Missing** on create and on trace ingest | Import dispatch limits in-flight work, which is half of it. Create endpoints still enqueue without looking at depth. Slot acquire fails open | The broker grows without bound while the API returns 202. Users keep clicking |
| Lease / leader election | A worker owns a unit of work until a heartbeat dies, then someone else takes it | **Partial** | Platform import uses sorted-set leases. Eval slots are a single integer. Simulation runs have no lease. Beat is a single process with no durable lock around the schedule | Stuck `RUNNING`, leaked slots, double cron fires after a restart |
| Outbox | Write the business row and the "please do this next" event in the same transaction. A dispatcher publishes it | **Missing** | Code calls `task.delay()` after a commit, or before, depending on the path. Rebalance copies, commits, then deletes, and can delete if the publish step failed | A crash between commit and enqueue loses the job, or a crash after enqueue and before commit runs a job for a row that does not exist |
| Saga | A long flow has a forward step and a compensate step per stage | **Missing** for simulations and outbound | Status strings move forward. Compensate is "set FAILED" in some tasks and missing in others. Harbor has no resume | You cannot undo a half-placed call or resume a run after a deploy. Each stage needs `forward` and `compensate` |
| Quota / rate limit object | One implementation of "this tenant has spent its budget" | **Partial** | Trace limiter, telephony recording limiter, OSS quotas, eval slot caps. Each is its own mechanism, and some fail open | The next feature invents a fifth limiter and forgets fail-closed. One `Budget.try_acquire(tenant, kind)` |
| Cache-aside with a key that includes tenancy | Cache is keyed by tenant. Miss loads. Expiry is explicit | **Partial** | API-key cache and trace correlation cache exist. TTLs expire mid-call and mint a second trace. Frontend cache keys often omit workspace | Cross-tenant data on screen. Duplicate traces. Stale catalog. Key = tenant + id, TTL longer than the operation, invalidate on write |
| Anti-corruption layer | Our model stays stable when a vendor payload changes | **Partial** | OTLP mapper is a layer (`otlp_mapper.py`). Several webhooks store the raw vendor payload onto our call row and read fields from it later | A vendor field rename breaks alerts and the UI. Map at the edge into our types. Persist ours |

## C7. Frontend patterns (same ideas, UI names)

| Concept | Pattern | Status | What to standardise |
| --- | --- | --- | --- |
| One-way data flow | State lives in a store or a query cache. The screen renders it | **Partial** | React Query is the default. Platform admin uses `useEffect` and a second copy of loading/error. Ban new `useEffect` fetches |
| Container and presenter | The hook fetches. The component draws | **Missing** on the large pages | The page does both, so a visual change risks a request change. `useX(workspaceId)` returns data. The component takes props |
| Colocation / feature module | A feature's API, keys, hooks, and components sit together | **Partial** | `pages/callImports/components` exists. API calls still live in the global client and in the page | `features/imports/{api,keys,hooks,components}` |
| Query-key factory | Keys are a function, not a hand-written array | **Missing** | `['ai-providers']` and `['aiproviders']` | `keys.providers.list(workspaceId)` |
| Suspense / error/empty as states, not as blank | Loading, empty, and error are three renders | **Missing** on many lists | A failed load looks like "no data", and metrics then seed defaults | Every list component handles `isError` |
| Virtualization | Only draw the rows on screen | **Missing** | No virtualization library in the frontend | Required the day a table is not paged. Until then, server paging is the pattern. Do not render 500 cards |
| Code splitting | Load the code for the route the user opened | **Missing** | One 5.5 MB chunk. Static imports in `App.tsx` | `React.lazy` per route. Voice SDKs load with the playground only |
| Optimistic update vs refetch-the-world | After a write, update the one key or invalidate that key | **Partial** | Some mutations invalidate a key. Workspace switch invalidates everything | Invalidate the key you wrote. Full clear only on logout |
| Render nothing you did not ask for | A parent re-render should not redraw a heavy child | **Missing** | Layout state and the walkthrough context re-render the current page, including 4,500 line screens | Split chrome from the outlet. Pass stable props. Memoize the heavy child |

## C8. Do not add these

These are real patterns. They are the wrong tool here. Adding them to "follow LLD" would make the junk worse.

| Pattern | Why it is the wrong tool |
| --- | --- |
| Generic repository base class | Hides the query you need to see. A named function per query is the repository |
| Visitor | We do not have a stable object tree that needs many new operations. Metric rendering is a builder |
| Interpreter | Prompts are not a language runtime. Do not build one |
| Prototype / clone | Nothing expensive is copied per request that way |
| Memento | We do not snapshot arbitrary object graphs. Status plus an event row is enough |
| Active record everywhere | The model that saves itself from a route is how SQL leaked into the routes. Keep persistence in the query module |
| A project-wide event bus | Observer for "row finished" and "call ended" is enough. A bus for every write becomes undebuggable |
| Full CQRS (a second write model for every table) | One rollup for charts and alerts, plus ClickHouse for spans. Not a second database per feature |
| Deep inheritance trees | `BaseVoiceProvider` is already too wide. Prefer a small protocol and composition |

## C9. The short list that will actually break us

If the team adopts nothing else, these are the patterns whose absence is already a defect, not a future risk.

1. **Strategy + registry** for every vendor and every metric dialect. Copy `get_voice_provider` and `HistoricalProviderAdapter`. Stop adding `if provider` in routes and in `llm_evaluation.py`.
2. **State machine with explicit transitions** for runs, import rows, and traces, including the timeout edge. Status strings with no owner are why runs stick on `RUNNING`.
3. **Command with an idempotency key** on create-run, webhooks, and outbound dial.
4. **Unit of work**: one commit per action, no vendor HTTP inside the transaction, no per-row commit in a loop.
5. **DTO per screen**: list, chart, and detail are different shapes. Delete the path that returns the fat row to a list or a poll.
6. **Observer** from the judge and the call-ender. They emit an event. Billing, eval, and the UI subscribe.
7. **Circuit breaker + fail-closed lease** around every vendor and every slot. Retry without these fills the workers.
8. **Outbox** between "row committed" and "task enqueued".
9. **Query-key factory and feature hooks** on the frontend, so a new page cannot forget the workspace or fire a second catalog request.
10. **One reason to change per file.** The open/closed rule is unenforceable while the use case lives in a 10,000 line module.

We already follow factory, adapter, strategy, template method, middleware chain, and pub/sub in the parts of the code that were given a package of their own. The breaks are in the parts that kept growing in the route and the page. New features go through the ten above. If a pull request cannot name which of the ten it used, it is extending the junk.

---

# Part D — What the rest of the report does not cover

Parts A–C follow the sidebar and the pattern list. A few risks do not belong to one screen, and they are easy to miss because the code looks fine until a customer asks a question the product cannot answer. This part is those gaps. It also corrects one understatement: the backend is not untested.

## D1. The backend test suite is a real asset

`tests/` holds on the order of **400 test modules**. Pull requests to `main` run them against Postgres (`.github/workflows/backend-tests-postgres.yml`). Coverage is uneven, and it is strongest where someone already extracted a function: judge parsing, fair dispatch, call-import routes, sharding, telephony URL checks, Flexprice, auth cookies.

The frontend is the opposite. About **17** test files, almost all pure helpers. Nothing in CI fails when a React Query key drops the workspace id. Docs CI runs a frontend check (`.github/workflows/docs.yml`); it does not protect tenancy.

**Do not** start a project to "add tests" in the abstract. When a use case is extracted (Part B), the test lands on that function in the same pull request. The first frontend tests worth writing are: query keys include workspace id, a 401 triggers one refresh, and a failed list does not render as empty.

## D2. Two people editing the same thing

There is no version column, no `ETag`, and no "updated at matches what I loaded" check on the aggregates people edit: agents, metrics, prompts, alert rules, integrations. The last save wins. The first person's change disappears with no error.

At one editor this is rare. The day a second teammate joins an account, it becomes a weekly incident, and it looks like a bug in the feature rather than a missing lock.

**Change.** On each editable aggregate, store `updated_at` or an integer version. The save sends the version it read. The update is `WHERE id = ? AND version = ?`. Zero rows means 409 conflict, and the UI reloads. Do this on the next entity you touch, then copy it. Do not boil every table in one migration.

## D3. Data lifetime, offboarding, and PII

The product stores call audio, transcripts, scores, and spans. The report's scale numbers assume that data stays. The product has almost no policy for letting it go.

- ClickHouse trace tables have **no TTL** (Part A). A year of spans is tens of billions of rows if you keep them.
- Postgres call rows, import rows, and recordings have no retention job. Usage history has a pruner for the OSS rollup (`prune_oss_usage_history`). Customer call data does not.
- A search for deleting an organisation on the platform-admin route does not find a cascade. Offboarding a tenant means a person knows every table, every shard, and every S3 prefix. They will miss one.
- Transcripts and `call_data` are personal data. They are allowed in the database and in object storage. They are not allowed in application logs, error trackers, or analytics. There is no single helper that redacts them, so the next `logger.exception(row)` is an incident.

**Change.** Write the policy in one place, then make the code match it: how long a trace span lives, how long a recording lives, how long a scored row lives, and the one job that deletes an organisation (catalog, every shard, every object prefix, ClickHouse). Until that job exists, "delete my account" is a manual project. Add a test that a log formatter cannot emit `call_data` or a transcript field.

## D4. A click that succeeds before the data exists

Several doors return before the work is visible: trace ingest returns 202 after an S3 put, simulation create returns after enqueue, imports return after staging. The UI then reads a store that may not have the row yet. Users refresh, double-submit, or think it failed.

**Change.** Each of those responses includes a stable id and a status URL that is cheap (`queued`, not the full row). The button stays pending until that status exists. Create endpoints take an idempotency key (Part C) so the refresh is safe. This is the contract between the screen and the queue. Write it down per action. Do not leave it as "the poll will probably see it".

## D5. Jobs that fail and then vanish

Celery is configured with `acks_late` and `reject_on_worker_lost`. A crash redelivers the task. That is right. After `max_retries`, the message is gone. There is no dead-letter queue and no single screen of "poisoned" work. The row's status is the only record, and only if the task remembered to set it. Simulation runs do not (Part A): they stay `RUNNING`.

**Change.** One outcome for every task: `succeeded`, `failed` with a reason on the row, or `retry`. A task that exits without writing one of those is a bug. A small admin query — rows stuck in a non-terminal status past their lease — is the operator view. A dead-letter queue is optional once the row itself holds the failure.

## D6. Rolling deploys will fight the schema

Part A says migrations must run once, under a lock. That is not enough. During a Kubernetes rollout, old pods and new pods run together. A migration that adds a `NOT NULL` column, renames a column, or changes a row's meaning will crash the pods that have not restarted.

**Change.** Every schema change is expand, then code, then contract. First add the new column as nullable and write both shapes. Next release reads the new shape. A later release drops the old one. Never rename a column the previous release still reads. The migration Job runs before the new pods take traffic, and the old pods must still boot against the expanded schema. Put this in the pull-request checklist next to the ten patterns. One bad migration takes the API down in a way that more replicas make worse, because they migrate and serve at the same time today.

## D7. Three configs, three products

The same behaviour is set in `config.yml`, in environment variables, and in Python defaults, and they disagree. `DEBUG` defaults true in code and false in the Docker config. Sharding is on in a local config and off in `config.docker.yml`. ClickHouse is commented out in the example, and trace ingest then returns 503. A new pod that misses one variable is a different product.

**Change.** One source wins: environment in the cluster, file only for local. Boot must fail when `DEBUG` is true, the secret is the placeholder, or trace ingest is enabled without ClickHouse. Print the effective values that matter (pool sizes, slot caps, sharding on or off, ClickHouse on or off) in the startup log. If two pods print different lines, you are not running one system.

## D8. A tenant can spend without a ceiling

Slot caps limit concurrency. They do not limit money. A simulation run, an import, and a cron job all call the LLM until the queue is empty. Optimization has `max_metric_calls`. Nothing else has a budget. One mis-clicked "run" on a large import is a bill, and a shared provider key means it is also everyone else's latency.

**Change.** A budget object per organisation: tokens or judge-calls per day, checked when a trial or a row is claimed, not after the invoice. When it is spent, the rest of the queue fails with a clear status. The Usage page reads that budget. Flexprice stays a subscriber (Part B), not the thing that stops the worker.

## D9. Tenant isolation is a query rule, not a middleware hope

The workspace header is stamped on the client. The server must still ignore it when the caller is not a member, and every query must include the organisation or the workspace. Middleware that sets "current workspace" does not protect a query someone wrote without the filter. Sharding makes this worse: a bug can read another tenant's slice if the id is guessed and the query is not scoped. Public ids are 6 digits today, which makes guessing cheap (Part A).

There is a security test file and enterprise-gating tests. There is not a habit that every new list query arrives with a test that a second organisation sees zero rows.

**Change.** The query functions from Part B take `organization_id` as a required argument, not an optional filter. A test template: create two orgs, call the function as org A, assert org B's row is absent. Apply it to calls, imports, traces, runs, and API keys first. Those are the tables that hold customer data.

Recording download already has the right instinct: `assert_recording_url_safe` rejects IP hosts, credentials in the URL, non-allowlisted hostnames, and private addresses after DNS resolution (`app/services/telephony/recording_download.py`). Keep every new outbound fetch on that helper. A CSV full of URLs is otherwise a way to make the worker call the internal network.

## D10. You cannot see which tenant is hurting you

Part A notes that Prometheus scrapes one API address and does not see workers. The missing product view is per organisation, not per pod: queue wait, LLM calls, error rate, ingest lag, slots in use. Without it, a noisy tenant and a broken deploy look the same, and the only tool is reading logs.

**Change.** Four numbers, emitted by the workers you already have, labeled by organisation id:

- Age of the oldest queued trial, import row, and trace batch.
- Slots in use against the cap.
- Judge calls and tokens in the last hour (the Redis counters already exist).
- API error rate.

Page on queue age and on error rate. The dashboard in the product can show the same counters later. Do not build the chart before the numbers exist.

Define the targets in one sentence each, so "scale" is a yes or no: API p99 under a second for anything that is not a file, trace ingest lag under a minute, no run left non-terminal more than ten minutes after its lease died, a list endpoint never reads a transcript. The load test in Part A measures these. It does not invent new ones.

## D11. The frontend and the backend do not share a contract

FastAPI can emit an OpenAPI document. The client does not generate from it. `api.ts` and `types/api.ts` are hand-written, full of `any`, and they drift. A renamed field becomes a silent `undefined` on a screen. That is how extra requests and blank states sneak in: the UI asks again, or it asks for the wrong shape and then fetches a second endpoint to fill the hole.

**Change.** Generate the client types from the OpenAPI schema in CI, and fail the build when the committed types are stale. Start with the hot resources: calls, imports, simulation runs, traces. Hand-written wrappers can stay for auth. New endpoints do not get a new `any` method.

## D12. What this report is not

- It is not a load test. Every ceiling is arithmetic from caps in the repo.
- It is not a penetration test. Tenant-filter tests and the recording URL allowlist are the security items tied to scale. Auth cookies, CSRF, and security headers already have tests. Someone should still try cross-tenant ids on purpose before a public launch.
- It is not a line-by-line inventory of every button. The controls that fan out, poll, or silently truncate are covered. A button that saves one row is fine unless it is missing a version check (D2) or an error state (Part B).
- It does not know your replica counts, backup frequency, or restore drill. Those are not in the repository. The code gap that remains even with perfect backups is D3: you cannot restore or delete **one** organisation. A cluster backup is not a tenant export.

Revisit this document when one of the ten patterns in Part C becomes the default for new code, or when a load test replaces a ceiling with a measurement. Until then, treat a contradiction between this file and the code as a bug in one of them, and fix the one that is wrong.
