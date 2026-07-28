# CLAUDE.md — Generic Data Ingestion Service

**Purpose of this file:** This is the persistent project brief and build plan for the "Generic Data Ingestion Service" take-home assignment (Intentwise, AI-Native Software Engineer role, first round). Claude Code should re-read this file at the start of every session in this project. It is self-contained — do not assume any other context exists. Every requirement in the "Hard Requirements Checklist" is binding unless the project owner explicitly says otherwise in conversation. Nothing here should be silently dropped, softened, or summarized away as work proceeds.

---

## 1. Project Overview

We are building a service that can pull data out of *any* external API and store it somewhere durable, without being written for that one API. Instead of hardcoding "how to talk to API X," the service reads a config that describes a source (its base URL, how it authenticates, how it paginates, and roughly what its responses look like), and a generic engine uses that config to fetch, paginate through, and persist the data. Adding a new source should mean writing a new config file, not new application code (unless the new source introduces a genuinely new auth or pagination *style*, in which case only a small, isolated new strategy class should be needed). The storage side is similarly pluggable: a database sink today, with object storage (e.g., S3) added later as a second implementation of the same interface. The system must be demoed end-to-end against two real public APIs that differ in both auth style and pagination style, to prove the generality is real and not coincidental. Because these are treated as real production APIs, the design must visibly account for rate limiting, retries/backoff, partial failures, idempotency, schema drift, timeouts, and observability — to a depth that's justified and explained, not maximized blindly, given the ~2-day time box.

---

## 2. Hard Requirements Checklist

Nothing in this list may be dropped without the project owner's explicit sign-off.

### Core Behavior
- [ ] Accept one or more API endpoints as input/configuration (not hardcoded).
- [ ] Work out how to pull data from a source (auth style, pagination style, response shape) in a generic, config-driven way — not hardcoded per source.
- [ ] Download the data from the configured source(s).
- [ ] Persist downloaded data to a database.
- [ ] Design makes it easy to add a new data source without rewriting the application (config-first; new code only for genuinely new auth/pagination styles).
- [ ] Design makes the destination pluggable — straightforward to extend beyond a database to object storage (e.g., S3) later.
- [ ] Demoed against at least two structurally different public APIs (different auth style **and** different pagination style) to prove genuine generality.
- [ ] Realistic production concerns are explicitly addressed and the depth of each is documented and justified: auth handling, pagination, rate limiting/backoff, retries, partial failures, error handling, idempotency, logging/observability, schema variability, timeouts, config validation.

### Constraints
- [ ] Language is Java or Python — **default: Python**, unless the project owner says otherwise (see Open Questions).
- [ ] Total time budget is ~2 days; scope is realistic for that budget and prioritizes core generality over feature count.
- [ ] No hardcoding to a single API anywhere in the core ingestion path.

### Deliverables
- [ ] Git repository with real, incremental, meaningful commit history (not one giant commit).
- [ ] GitHub user **hrintentwise** granted read-only access to the repository.
- [ ] A `docker-compose` that runs the whole thing (app + Postgres) with a single command — this ships **regardless**, since Postgres-only means it is the supported way to run the project, not just a hosting fallback.
- [ ] A hosted, callable endpoint to trigger and observe ingestion (strongly preferred, attempted on top of the above; falls back to compose-only if it eats the time box).
- [ ] A working demo against at least two structurally different public APIs (different auth + different pagination).
- [ ] README / design note with these sections, each present on its own:
  - [ ] How to run it
  - [ ] The public API(s) used
  - [ ] Architecture and key design decisions
  - [ ] Tradeoffs and assumptions
  - [ ] What I would do with more time
  - [ ] A short note on how AI tools were used, including one concrete place the AI got something wrong and how it was caught

### Evaluation Criteria (design should visibly optimize for these)
- [ ] Clear, extensible design and sound engineering judgment, prioritized over sheer feature count.
- [ ] Solution visibly handles the realities of pulling data from live APIs.
- [ ] Solution is correct and can actually be run and tested by the evaluator.
- [ ] Decisions and tradeoffs are clearly communicated in the README.

---

## 3. Architecture

**High-level flow:** `SourceConfig` → `AuthStrategy` + `PaginationStrategy` → `Fetcher` → normalized records → `Sink` (pluggable) → `JobRun` metadata recorded.

### 3.1 Source config (the DSL)
Each source is described by a config file (YAML or JSON) validated against a Pydantic schema. Proposed shape:

```yaml
source_id: rick_and_morty_characters
base_url: https://rickandmortyapi.com/api
endpoint:
  path: /character
  method: GET
  static_params: {}
auth:
  type: none            # none | api_key | bearer_token | oauth2_client_credentials
  config: {}
pagination:
  type: next_url_in_body   # next_url_in_body | offset_limit | page_number | link_header | cursor_field
  config:
    next_url_json_path: "info.next"
    records_json_path: "results"
response:
  record_id_field: id
  raw_storage: true        # store raw payload alongside normalized fields
rate_limit:
  requests_per_second: 2
  burst: 4
retry:
  max_attempts: 5
  backoff_base_seconds: 1
  backoff_max_seconds: 30
timeout_seconds: 15
destination:
  sinks: [database]        # database | s3 (future)
```

Adding a new source = adding a new file like this. No code change needed as long as the auth/pagination types already exist as strategies.

### 3.2 Auth strategy abstraction
`AuthStrategy` interface: `apply(request: RequestSpec) -> RequestSpec` (injects headers/query params/tokens before a request is sent; may also handle token refresh for OAuth2 client-credentials).
Planned implementations:
- `NoAuth`
- `ApiKeyAuth` (query param or header, configurable key name)
- `BearerTokenAuth` (static token from config/env)
- `OAuth2ClientCredentialsAuth` (fetches + caches a token, refreshes on 401/expiry) — stretch, only if time allows.

### 3.3 Pagination strategy abstraction
`PaginationStrategy` interface: given the current request and the last response, yields the next `RequestSpec` or signals "done." Implemented as an iterator/generator so the Fetcher loop doesn't know or care which style it's driving.
Planned implementations:
- `NextUrlInBodyPagination` (response contains a full "next page" URL, e.g. `info.next`)
- `OffsetLimitPagination` (increment offset/page query params until an empty page)
- `LinkHeaderPagination` (RFC 5988 `Link` header with `rel="next"`, e.g. GitHub's API)
- `PageNumberPagination` (simple `?page=N`)
- `CursorFieldPagination` (opaque cursor token in the response body) — stretch if a demo API needs it.

### 3.4 Fetch/download layer
`Fetcher` orchestrates: builds the initial request from `SourceConfig`, applies `AuthStrategy`, executes via an async HTTP client (`httpx`), applies rate limiting (token bucket keyed by source), retries transient failures with exponential backoff + jitter (`tenacity`), respects `Retry-After` headers where present, enforces per-request timeouts, and logs each request/response at a structured level (source_id, url, status, latency, attempt count). On each successful page, hands raw + normalized records to the sink layer in batches; on a page that exhausts retries, the failure is recorded against the job run and the loop continues to the next page where possible (partial-failure isolation) rather than aborting the whole run.

### 3.5 Pluggable storage/sink abstraction
`Sink` interface: `write(records: list[NormalizedRecord], source_id: str, run_id: str) -> WriteResult`.
- `DatabaseSink` (v1, required): **Postgres only**, via SQLAlchemy 2.0. Upserts on `(source_id, record_id)` using Postgres `INSERT ... ON CONFLICT DO UPDATE` for idempotency; stores the raw JSON payload in a `JSONB` column alongside normalized columns to absorb schema drift without hard failures. There is no SQLite fallback — Postgres is always supplied by `docker-compose`, including for local dev and tests, so there is exactly one database code path and it is the one that gets demoed.
- `S3Sink` (interface + stub or minimal real implementation against local MinIO — decide based on time budget in Day 2): demonstrates the destination is genuinely pluggable, not just claimed to be.
- Multiple sinks can be attached to one source (`destination.sinks: [database, s3]`) — the Fetcher writes to all configured sinks per batch.

### 3.6 Orchestration / job layer
`IngestionJob(source_config)`: drives one end-to-end run, creates a `job_runs` row (status, started_at, finished_at, pages_fetched, records_written, records_failed, error_summary), streams through Fetcher → Sink(s), and updates the row incrementally so a run's status is observable mid-flight via the API.

### 3.7 API layer
A thin FastAPI service exposing:
- `POST /sources` — register/validate a source config
- `POST /ingest/{source_id}` — trigger a run (idempotent per `(source_id, trigger_key)` if a trigger key is supplied)
- `GET /runs/{run_id}` — run status + counts (observability)
- `GET /runs` — list recent runs
- `GET /healthz` — health check

### 3.8 Adding a new source (target UX)
1. Write a new config file describing the source.
2. If its auth/pagination style already has a strategy implementation → done, no code change.
3. If not → implement one small class against the existing `AuthStrategy`/`PaginationStrategy` interface; nothing else in the system changes.

### 3.9 Directory layout

Each abstraction in 3.1–3.7 gets its own package so a new strategy/sink is additive (one new file), never a change to an existing module. `main.py` only wires things together; it contains no source-specific logic.

```
generic-data-ingestion-service/
├── app/
│   ├── main.py                    # FastAPI app factory + startup (DB schema create, logging init)
│   ├── logging_config.py          # structured (JSON) logging setup
│   ├── config/
│   │   ├── schema.py              # Pydantic SourceConfig / AuthConfig / PaginationConfig / etc.
│   │   └── loader.py              # load + validate a YAML file into a SourceConfig
│   ├── auth/
│   │   ├── base.py                # AuthStrategy ABC — apply(request) -> RequestSpec
│   │   ├── none.py                # NoAuth
│   │   ├── api_key.py             # ApiKeyAuth (header or query param)
│   │   ├── bearer_token.py        # BearerTokenAuth (static token from env/config)
│   │   └── registry.py            # auth.type string -> strategy class lookup
│   ├── pagination/
│   │   ├── base.py                # PaginationStrategy ABC — iterator/generator of RequestSpec
│   │   ├── next_url_in_body.py    # NextUrlInBodyPagination (e.g. Rick and Morty info.next)
│   │   ├── link_header.py         # LinkHeaderPagination (RFC 5988, e.g. GitHub)
│   │   ├── offset_limit.py        # OffsetLimitPagination
│   │   ├── page_number.py         # PageNumberPagination
│   │   └── registry.py            # pagination.type string -> strategy class lookup
│   ├── fetch/
│   │   ├── request_spec.py        # RequestSpec value object (method, url, headers, params, body)
│   │   ├── rate_limiter.py        # token-bucket limiter keyed by source_id
│   │   └── fetcher.py             # orchestrates auth + pagination + httpx + tenacity retries + timeouts + logging
│   ├── sinks/
│   │   ├── base.py                # Sink ABC — write(records, source_id, run_id) -> WriteResult
│   │   ├── database_sink.py       # Postgres upsert via SQLAlchemy 2.0 ON CONFLICT DO UPDATE
│   │   └── s3_sink.py             # interface-only stub (see Section 9)
│   ├── db/
│   │   ├── models.py              # SQLAlchemy models: raw_records, job_runs, source_configs
│   │   └── session.py             # engine/session factory (Postgres only, from env)
│   ├── jobs/
│   │   └── ingestion_job.py       # IngestionJob — one end-to-end run, updates job_runs incrementally
│   └── api/
│       ├── routes.py              # POST /sources, POST /ingest/{source_id}, GET /runs/{run_id}, GET /runs, GET /healthz
│       └── schemas.py             # request/response Pydantic models for the API layer
├── configs/
│   └── sources/
│       ├── rick_and_morty_characters.yaml
│       └── github_issues.yaml
├── tests/
│   ├── test_auth_strategies.py
│   ├── test_pagination_strategies.py
│   ├── test_database_sink.py       # runs against the compose Postgres, not SQLite (see D-1)
│   └── conftest.py
├── docker-compose.yml              # app + Postgres, single-command run
├── Dockerfile
├── requirements.txt
├── .env.example
└── README.md
```

Rule of thumb enforced by this layout: adding a source is a new YAML file under `configs/sources/`; adding a new auth or pagination *style* is exactly one new file in `app/auth/` or `app/pagination/` plus one line in the corresponding `registry.py` — no existing file is touched. Adding a new destination is one new file in `app/sinks/` implementing the same `Sink` ABC.

---

## 4. Tech Stack & Key Decisions

| Area | Choice | Why |
|---|---|---|
| Language | Python | Default per assignment; fast to build config-driven/dynamic strategy dispatch, good async HTTP + typed-config libraries. |
| Web framework | FastAPI | Async-native (fits an I/O-bound ingestion workload), built-in request/response validation via Pydantic, auto-generated docs for the "hosted endpoint" deliverable. |
| Config validation | Pydantic v2 | Same validation model as FastAPI; gives us strict `SourceConfig` schema validation for free (covers the "config validation" concern). |
| HTTP client | httpx (async) | Async support, timeout controls, works cleanly with `tenacity` for retries. |
| Retry/backoff | tenacity | Declarative exponential backoff + jitter without hand-rolling retry loops. |
| DB | **Postgres only**, always via `docker-compose` (no SQLite fallback) | JSONB for raw-payload storage handles schema drift; native `ON CONFLICT` gives real upsert idempotency. A SQLite fallback would add a second, effectively untested storage path (different JSON handling, different upsert semantics, different type affinity) to save the evaluator a `docker compose up` they already have to run — a bad trade. One DB, one code path, and the demoed path is the only path. |
| ORM | SQLAlchemy 2.0 | Mature, explicit Postgres dialect support (`postgresql.insert(...).on_conflict_do_update`). Free to use Postgres-specific constructs now that portability is a non-goal. |
| Containerization | Docker + docker-compose | Required fallback deliverable if hosting isn't used; also makes local dev reproducible. |
| Hosting (if pursued) | Render or Railway (free/hobby tier) | Minimal-friction way to get a public callable endpoint without managing infra; fallback to docker-compose if this proves unreliable within the time box. |
| Logging | Python `logging` with structured (JSON) formatter | Cheap, dependency-light way to satisfy the "observability" concern without pulling in a full stack. |
| Testing | pytest, focused on strategy classes + sink upsert logic | Time-boxed; breadth over depth is not the goal — core generality logic (strategies) is what must be demonstrably correct. |

**Decisions still open / need your input:** see Section 9 (Open Questions).

---

## 5. Realistic API Concerns & Depth (2-day budget)

| Concern | Planned depth | Rationale |
|---|---|---|
| Auth handling | **Full** (pluggable strategies: none, API key, bearer token; OAuth2 client-credentials as stretch) | This is core to the "genericity" claim the assignment is testing — cannot be shallow. |
| Pagination | **Full** (pluggable strategies covering at least 2 real styles used in the demo, designed to extend to more) | Same as above — core to genericity. |
| Rate limiting / backoff | **Full** (token bucket per source + honoring `Retry-After`) | Explicitly called out as a "realistic concern" in the assignment; cheap to implement well with existing libraries. |
| Retries | **Full** (tenacity: exponential backoff + jitter, bounded max attempts, only on transient/5xx/429/timeout errors) | Same reasoning; low implementation cost relative to value. |
| Idempotency | **Basic** (Postgres `INSERT ... ON CONFLICT DO UPDATE` on a unique `(source_id, record_id)`; optional trigger-key idempotency for job triggers) | Enough to prevent duplicate records/reruns from corrupting state; full exactly-once semantics across distributed writers is out of scope for a single-process 2-day build. |
| Partial failure handling | **Basic** (per-page isolation — a failing page is logged and skipped/retried without aborting the whole run; job ends in a `partial_success` state with a failure summary) | Directly addresses "realities of live APIs" without building a full dead-letter/replay subsystem. |
| Schema drift | **Basic** (raw payload always stored as JSON alongside best-effort normalized fields; normalization failures are logged as warnings, not hard failures) | Cheap insurance against source APIs changing shape mid-run; full schema-versioning/migration tooling is out of scope. |
| Timeouts | **Full** (configurable connect/read timeouts per source, sane defaults) | Trivial to implement via httpx config; leaving it out would be an obvious gap on a "production APIs" framing. |
| Logging / observability | **Basic-to-full** (structured logs per request + a `job_runs` table exposed via API for run-level observability) | Enough to let an evaluator *see* what happened without building dashboards/metrics pipelines. |
| Secrets / config management | **Basic** (`.env` / environment variables locally; documented pattern for how a hosted secrets manager would replace this) | Full vault/KMS integration is disproportionate for a take-home; the pattern being sound matters more than the tooling. |
| **Explicitly out of scope** | Full S3 sink beyond an interface/stub (unless time allows a minimal MinIO-backed version); distributed/queue-based scaling; full OAuth2 authorization-code flow; multi-tenant auth on the ingestion API itself; comprehensive test coverage beyond strategy + sink logic; alerting/metrics dashboards | Named explicitly so the README can state these as conscious cuts, not oversights — this is itself part of what's being evaluated. |

---

## 6. Two Demo APIs (proposed — needs your confirmation)

1. **Rick and Morty API** (`https://rickandmortyapi.com/api/character`) — no authentication required; pagination via a full "next page" URL embedded in the response body (`info.next`). Good baseline: zero auth friction, body-embedded pagination style.
2. **GitHub REST API** (e.g. a public repo's `/issues` or a user's `/repos` endpoint) — authentication via a Bearer personal access token (or unauthenticated at a lower rate limit); pagination via the HTTP `Link` header (RFC 5988 cursor-style, opaque page URLs), and real rate limiting (5000 req/hr authenticated, 60/hr unauthenticated) — useful for also demonstrating the rate-limit/backoff handling in a real setting.

Together these differ in **both** auth style (none vs. Bearer token) **and** pagination mechanism (JSON-body next-URL vs. HTTP-header cursor), which satisfies the "structurally different" bar the assignment asks for. **Confirmed by project owner on 2026-07-28** — see Section 9.

---

## 7. Phased Build Plan for ~2 Days

### Day 1 — AM
- [ ] Init git repo, initial commit (this CLAUDE.md, license, .gitignore, project skeleton).
- [ ] Define `SourceConfig` Pydantic schema + config validation.
- [ ] Implement `AuthStrategy` interface + `NoAuth`, `ApiKeyAuth`, `BearerTokenAuth`.
- [ ] Implement `PaginationStrategy` interface + `NextUrlInBodyPagination`, `LinkHeaderPagination`.
- [ ] Commit incrementally per strategy/module (not one giant commit).

### Day 1 — PM
- [ ] Implement `Fetcher` (httpx + tenacity retries + timeout + rate limiting + structured logging).
- [ ] Stand up `docker-compose` with the Postgres service **first** (there is no SQLite fallback, so nothing runs locally without it); app container can be added later the same day.
- [ ] Implement DB schema (`raw_records` with `JSONB` raw payload, `job_runs`) + SQLAlchemy models.
- [ ] Implement `DatabaseSink` with Postgres `ON CONFLICT DO UPDATE` upsert idempotency.
- [ ] Wire end-to-end pipeline; run against demo API #1 (Rick and Morty) locally; verify data lands in DB correctly across multiple pages.
- [ ] Commit.

### Day 2 — AM
- [ ] Configure demo API #2 (GitHub) — validates the Link-header pagination + bearer-token auth strategies against a real, rate-limited API.
- [ ] Implement partial-failure isolation + `job_runs` status reporting.
- [ ] Build FastAPI endpoints (`/sources`, `/ingest/{source_id}`, `/runs/{run_id}`, `/runs`, `/healthz`).
- [ ] Write core pytest coverage for strategies + sink upsert logic (sink tests run against the compose Postgres, not an in-memory SQLite stand-in — otherwise the upsert path under test isn't the one that ships).
- [ ] Commit.

### Day 2 — PM
- [ ] Finish Dockerfile + docker-compose (app + Postgres, healthcheck + `depends_on` so the app waits for the DB, migrations/schema-create on startup); verify a genuine single-command run (`docker compose up`) from a clean clone with no local Postgres installed.
- [ ] Attempt hosted deploy (Render/Railway); fall back to docker-compose-only if it eats too much time.
- [ ] Stub or minimally implement `S3Sink` to prove sink pluggability, time permitting.
- [ ] Write README (all required sections — see Section 8).
- [ ] Finalize AI Usage Log (Section 10), including the required "AI got something wrong" example.
- [ ] Run final demo pass against both APIs; capture logs/output as evidence.
- [ ] Repo cleanup (remove dead code/debug artifacts; confirm commit history reads as incremental and meaningful).
- [ ] Grant GitHub user `hrintentwise` read-only access to the repo.
- [ ] Final pass against the Hard Requirements Checklist in Section 2 — confirm every box is either checked or consciously, explainably deferred.

---

## 8. README Outline (exact section headers required)

```
# Generic Data Ingestion Service

## How to run it
## The public API(s) used
## Architecture and key design decisions
## Tradeoffs and assumptions
## What I would do with more time
## How I used AI tools
```
(The last section must include one concrete instance where the AI got something wrong and how it was caught — pull this from Section 10 below.)

---

## 9. Open Questions for You

- [x] **Language:** **Decided: Python** (default per assignment rule).
- [x] **Hosting:** **Decided: attempt Render (free tier)** as the hosted endpoint, falling back to docker-compose-only if it eats the time box.
- [x] **Database:** ~~Postgres via Docker, or SQLite-only?~~ **Decided: Postgres-only via `docker-compose`, SQLite fallback dropped.** Rationale: the fallback bought a marginally faster local start in exchange for a second storage path that would never be exercised in the demo or tests. Recorded in Section 4 and Section 11.
- [x] **Demo APIs:** **Decided: Rick and Morty + GitHub**, as proposed in Section 6.
- [x] **GitHub auth for demo #2:** **Decided: use a real scopeless personal access token** (via env var), so `BearerTokenAuth` is genuinely exercised end-to-end (5000 req/hr), not just left unauthenticated.
- [x] **Repo visibility:** **Decided: public repo.** (No explicit collaborator invite needed for `hrintentwise`, though it can still be added if desired.)
- [ ] **S3 sink:** Defaulting to **interface-only stub** (per the time-box rationale in Section 5) unless told otherwise before Day 2 PM.
- [x] **Repo name:** **Decided: `generic-data-ingestion-service`.**

---

## 10. AI Usage Log (running — Claude Code should keep appending here throughout the build)

> This section feeds directly into the required README section "How I used AI tools." Keep entries brief: date/phase, what was AI-generated or AI-assisted, and whether it was accepted as-is, modified, or rejected. At least one entry **must** capture a concrete case where the AI got something wrong and how it was caught — do not leave this section without one by the end of the build.

| Phase | What Claude Code did | Outcome | Notes |
|---|---|---|---|
| _(fill in as work proceeds)_ | | | |

**Required — AI mistake caught (placeholder, must be filled in before README is finalized):**
`[TO FILL DURING BUILD] Describe: what the AI got wrong, how it was noticed, and what the fix was.`

---

## 11. Decision Log (amendments to this brief)

Signed-off changes to the plan above. Each entry is binding in the same way the original text is.

| # | Decision | Rationale | Consequences |
|---|---|---|---|
| D-1 | **Postgres-only. The SQLite fallback is dropped.** Postgres is supplied by `docker-compose` for local dev, tests, demo, and (if pursued) hosting. | The fallback added a second storage path — different JSON storage, different upsert semantics, different type affinity — that would never have been exercised by the demo or the tests, and it existed only to save the evaluator a `docker compose up` they already have to run for the app itself. Untested code path, no real benefit. | Free use of Postgres-specific constructs (`JSONB`, `ON CONFLICT DO UPDATE`). `docker-compose` moves to Day 1 PM and becomes the supported run path, not a hosting fallback. Sink tests run against real Postgres. README's "How to run it" documents exactly one route: `docker compose up`. No `sqlite` string appears anywhere in the codebase or config. |

| D-2 | Section 6 and Section 9 confirmed by project owner on 2026-07-28: Python, Postgres-only, Rick and Morty + GitHub as demo APIs, real PAT for `BearerTokenAuth`, Render for hosting attempt, public repo named `generic-data-ingestion-service`. | Unblocks application code per the gate below. S3 sink defaults to interface-only stub pending Day 2 PM time check. | Build proceeds per the Day 1/Day 2 phased plan in Section 7. |

*This is a live section — append a row here for any later decision that contradicts or narrows something written above, rather than silently editing the plan.*

---

*Application code may now begin — Section 6 and Section 9 were reviewed and confirmed by the project owner on 2026-07-28.*
