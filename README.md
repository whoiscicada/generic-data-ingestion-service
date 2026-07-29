# Generic Data Ingestion Service

A config-driven service that pulls data out of *any* external API and persists it durably, without being written for that one API. A source is described by a YAML config (base URL, auth style, pagination style, response shape); a generic engine reads that config to fetch, paginate, and persist the data. Adding a new source means writing a new config file, not new application code — unless the source introduces a genuinely new auth or pagination *style*, in which case only one small, isolated strategy class is needed.

**Live hosted endpoint:** https://generic-data-ingestion-service.onrender.com ([`/healthz`](https://generic-data-ingestion-service.onrender.com/healthz), [`/docs`](https://generic-data-ingestion-service.onrender.com/docs), [`/runs`](https://generic-data-ingestion-service.onrender.com/runs)). Deployed from [`render.yaml`](render.yaml) (free-tier web service + managed Postgres). Both demo sources have been run against it directly and land in its Postgres exactly as they do locally (42 pages / 826 records for Rick and Morty; 18 pages / 1800 records for GitHub issues) — see [How to run it](#how-to-run-it) below for the equivalent local commands against `docker compose up`, which remains the primary supported way to run this.

## How to run it

There are two ways to use this: call the already-running [hosted instance](#using-the-hosted-instance-instead), or run it yourself. For running it yourself, the only supported path is `docker compose up` — Postgres is always supplied by compose, for local dev, tests, and the demo alike.

```bash
git clone <this-repo>
cd generic-data-ingestion-service
cp .env.example .env   # then fill in GITHUB_TOKEN (see below)
docker compose up -d --build
```

That starts two containers:
- `db` — Postgres 16, exposed on host port **5433** (not 5432 — see [Tradeoffs and assumptions](#tradeoffs-and-assumptions))
- `app` — FastAPI service on `http://localhost:8000`, schema auto-created on startup, both demo source configs loaded from `configs/sources/`

Check it's up:

```bash
curl http://localhost:8000/healthz
# {"status":"ok"}
```

Trigger an ingestion run and inspect it:

```bash
curl -X POST http://localhost:8000/ingest/rick_and_morty_characters -d '{}'
# {"run_id":"...","source_id":"rick_and_morty_characters"}

curl http://localhost:8000/runs/<run_id>
# {"status":"success","pages_fetched":42,"records_written":826,"records_failed":0,...}

curl http://localhost:8000/runs        # recent runs
```

Interactive API docs: `http://localhost:8000/docs`.

### Using the hosted instance instead

The same API is live at **https://generic-data-ingestion-service.onrender.com** — no setup needed, just swap the base URL:

```bash
curl https://generic-data-ingestion-service.onrender.com/healthz

curl -X POST https://generic-data-ingestion-service.onrender.com/ingest/rick_and_morty_characters -d '{}'
curl https://generic-data-ingestion-service.onrender.com/runs
```

It's on Render's free tier, which **spins the instance down after a period of inactivity**. The first request after a period of idleness will hang for something like 30-60 seconds while it cold-starts back up (a Render hosting-tier characteristic, not an application issue) — if a request seems to hang, that's why; it responds normally once it's warm, and stays warm as long as it keeps getting traffic. `docker compose up` (above) doesn't have this problem and remains the primary supported way to run and evaluate this.

### GitHub token

The `github_issues` source uses `BearerTokenAuth`, so it needs a real personal access token in `.env`:

```
GITHUB_TOKEN=github_pat_...   # a plain, scopeless classic or fine-grained token is enough
```

It only reads public issues, so no scopes/permissions are required — the token exists purely to get the authenticated rate limit (5000 req/hr vs 60 req/hr) and to exercise `BearerTokenAuth` against a real token rather than leaving it unauthenticated.

### Running tests

Tests run against the same Postgres compose brings up (no SQLite stand-in, per the same reasoning as the app itself):

```bash
docker compose up -d db
export DATABASE_URL=postgresql+asyncpg://ingestion:ingestion@localhost:5433/ingestion
pip install -r requirements.txt
pytest -q
# 24 passed
```

## The public API(s) used

Two APIs, chosen to differ in both auth style **and** pagination mechanism:

| | Rick and Morty API | GitHub REST API |
|---|---|---|
| Endpoint | `GET https://rickandmortyapi.com/api/character` | `GET https://api.github.com/repos/encode/httpx/issues` |
| Auth | None | Bearer token (personal access token) |
| Pagination | Full "next page" URL embedded in the response body (`info.next`) | RFC 5988 `Link` header (`rel="next"`), cursor-based |
| Config | [`configs/sources/rick_and_morty_characters.yaml`](configs/sources/rick_and_morty_characters.yaml) | [`configs/sources/github_issues.yaml`](configs/sources/github_issues.yaml) |
| Verified live | 42 pages, 826 records | 18 pages, 1800 records (`state=all`, `per_page=100`) |

`encode/httpx` (not `microsoft/vscode`, the originally-proposed repo) was chosen for the GitHub source specifically because `state=all` on a repo the size of vscode is 100k+ issues — real, but impractical to fully paginate for a demo. httpx has enough issues to genuinely exercise multi-page Link-header pagination in well under a minute.

Both runs, plus an idempotency check (re-triggering `rick_and_morty_characters` with the same `trigger_key` returned the same `run_id` in ~50ms instead of re-crawling), were verified against the live APIs, not mocks, immediately before writing this README.

## Architecture and key design decisions

```
SourceConfig (YAML, Pydantic-validated)
    -> AuthStrategy   (app/auth/)        -- injects headers/params/tokens
    -> PaginationStrategy (app/pagination/) -- drives the page loop, extracts records
    -> Fetcher (app/fetch/)              -- httpx + tenacity retries + rate limiting + logging
    -> Sink(s) (app/sinks/)              -- pluggable destination(s)
    -> IngestionJob (app/jobs/)          -- orchestrates one run, writes job_runs
    -> FastAPI (app/api/, app/main.py)   -- /sources /ingest /runs /healthz
```

**Config-first, strategy-pattern core.** `SourceConfig` (Pydantic) is the DSL. `AuthStrategy` and `PaginationStrategy` are each an ABC plus a registry mapping a `type` string from config to a concrete class (`app/auth/registry.py`, `app/pagination/registry.py`). The `Fetcher` only ever calls the ABC's methods — it has no idea whether it's driving no-auth/body-URL pagination or bearer-token/Link-header pagination. This is what makes adding a source a config change, not a code change, and it's the thing the two-API demo is meant to prove is real.

**Fetcher (`app/fetch/fetcher.py`).** Builds the first request from config, applies `AuthStrategy` fresh on every attempt (not just the first — so a future token-refresh strategy would work without changing the Fetcher), rate-limits via a per-source async token bucket, retries 429/5xx/timeout/transport errors via `tenacity` (exponential backoff + jitter, honoring `Retry-After` when present), and enforces a configurable per-request timeout. It yields one `PageResult` per page so the caller can isolate a failing page without losing pages already fetched. A hard `max_pages` safety cap (10,000, see [How I used AI tools](#how-i-used-ai-tools)) guards against a source whose pagination never terminates.

**Sinks (`app/sinks/`).** `Sink` is an ABC with one method, `write(records, source_id, run_id, record_id_field)`. `DatabaseSink` upserts into `raw_records` via Postgres `INSERT ... ON CONFLICT (source_id, record_id) DO UPDATE`, which is where idempotency actually lives — re-running a source (or re-processing an overlapping page after a retry) updates existing rows instead of duplicating them. `S3Sink` is an interface-only stub: it exists to prove the destination is genuinely pluggable (same ABC, zero changes anywhere else) without spending the time budget on a real MinIO integration. A source can list multiple sinks (`destination.sinks: [database, s3]`) and the job writes each page to all of them.

**Schema drift.** `raw_records` stores the full raw JSON payload in a `JSONB` column alongside a couple of normalized columns (`source_id`, `record_id`). A record missing its configured `record_id_field` is logged as a warning and counted as failed, not a hard crash — the rest of the batch still gets written.

**IngestionJob (`app/jobs/ingestion_job.py`).** Creates a `job_runs` row up front, streams `Fetcher` pages into all configured sinks, and updates `pages_fetched`/`records_written`/`records_failed` after every page — so `GET /runs/{run_id}` reflects a run's progress while it's still in flight, not just after it finishes. A page-level or sink-level failure is caught, counted, and logged; it does not abort the run. The run ends `success` (no failures), `partial_success` (some pages/records failed but at least one page landed), or `failed` (not even the first page could be fetched). Idempotency at the *trigger* level: `IngestionJob(..., trigger_key=...)` checks for an existing `job_runs` row with the same `(source_id, trigger_key)` before doing any work, so re-triggering the same logical run (e.g. a scheduler retrying after a timeout) returns the original run instead of re-fetching everything.

**Observability.** Structured JSON logs (`app/logging_config.py`) on every fetch attempt — source, URL, status, latency, attempt number — plus `job_runs` as a queryable run-level view via the API. This is the "basic-to-full" depth called out in the brief: enough to see exactly what happened during a run without standing up a metrics/tracing stack.

## Tradeoffs and assumptions

- **Postgres only, no SQLite fallback, by deliberate decision.** A SQLite path would only ever be exercised locally, never in the actual demo — an untested code path (different JSON handling, different upsert semantics) that exists purely to save a `docker compose up`. One database, one code path, and it's the one that's actually tested and demoed.
- **Host Postgres port is 5433, not 5432.** The build machine already had a native Postgres 17 service bound to 5432; compose's `db` service is mapped to `5433:5432` on the host to avoid silently connecting to the wrong database (this exact collision happened once during the build — see below). Only the host-side port changed; the app talks to `db:5432` inside the compose network, unaffected.
- **`max_pages` safety cap (10,000), not unlimited pagination.** A misconfigured or genuinely buggy source (a "next" cursor that never advances) must not be able to consume resources forever. This is a blunt instrument, not a smart one — it just guarantees a hard stop.
- **Idempotency is "good enough for a single-process 2-day build," not exactly-once.** `ON CONFLICT DO UPDATE` on `(source_id, record_id)` handles re-runs and overlapping retries correctly. It does not handle concurrent writers racing on the same record in ways that require ordering guarantees, and there's no distributed lock preventing two overlapping triggers without a shared `trigger_key` from both fetching the same source concurrently (harmless here, since upserts are idempotent, but wasteful).
- **Partial-failure isolation is page-level, not record-level.** If a page exhausts its retries, the run stops paginating further (there's no way to know the next cursor without a successful response) but keeps whatever pages already landed and marks the run `partial_success`. This is "basic" depth per the brief, not a full dead-letter/replay subsystem.
- **S3Sink is a stub, not a real integration.** It proves the `Sink` ABC is genuinely pluggable; it deliberately does not touch real S3/MinIO, per the time-box call in the brief.
- **GitHub demo repo (`encode/httpx`) was swapped from the originally-proposed `microsoft/vscode`** because `state=all` on vscode is 100k+ issues — real pagination, but not a demo you'd want to sit through.
- **The Render free-tier instance spins down after inactivity** — see [Using the hosted instance instead](#using-the-hosted-instance-instead) for what that means in practice. `docker compose up` remains the primary, always-warm way to run and evaluate this.
- **Config validation is fail-fast and unforgiving.** An invalid `SourceConfig` (missing required auth/pagination fields, bad backoff bounds, etc.) raises a clear Pydantic validation error at load time, not a confusing failure mid-run.

## What I would do with more time

- Real `S3Sink` against MinIO, proving pluggability with working code instead of an interface.
- OAuth2 client-credentials `AuthStrategy` (token fetch + cache + refresh-on-401), since bearer/API-key/none covers the common cases but not the token-refresh case.
- `CursorFieldPagination` for APIs whose cursor is an opaque body field rather than a full URL or a header.
- Record-level (not just page-level) partial-failure handling, so a single malformed record doesn't need the whole page re-fetched on retry.
- A real metrics surface (request counts/latencies/error rates per source) rather than relying on grepping structured logs.
- Background/async job execution instead of the current synchronous-within-the-request `await job.run()` — fine for a demo, but a real long-running crawl (the GitHub one already takes ~25s) shouldn't block an HTTP response.
- A CLI/scheduler wrapper so ingestion can run on a cron without an external trigger hitting the API.

## How I used AI tools

I built this using Claude Code (Anthropic's CLI agent) as my implementation tool, working from a detailed project brief (`CLAUDE.md`) I wrote up front myself — the requirements checklist, architecture, tech-stack decisions, and phased build plan were my own instructions to the assistant, not something it invented on its own. I kept `CLAUDE.md` out of this repo on purpose (it's my internal brief/scratchpad for driving the build, not deliverable content) — it got committed once by mistake early on, and I had that reverted as soon as I caught it.

I didn't leave this unattended. Before any code was written, I settled the brief's open questions myself — which two APIs to demo, whether to actually exercise a real GitHub token vs. staying unauthenticated, which hosting platform to attempt, public vs. private repo — and only then let the corresponding code get written. I reviewed and approved every file the assistant generated before accepting it, and caught a few things along the way: I required a fix to the commit convention (no AI co-author attribution), had the internal brief file untracked from the repo, and made the real infrastructure calls myself in real time — providing the GitHub token used by the live demo, installing Docker Desktop mid-build when it turned out not to be available in the assistant's environment, and confirming the Postgres port remap after a collision with a pre-existing local service on my machine.

Four concrete mistakes were caught during the build:

1. **A test bug that exposed a real gap.** While writing a respx-mocked test for multi-page pagination, the test hung indefinitely with climbing memory. The immediate cause was a test-authoring mistake (two mocked routes for the same path differing only by query string, which respx's default matching ignores, so the wrong mock kept matching). But that bug exposed a real production gap: the Fetcher's page loop had no upper bound, so a source whose "next" cursor never advances could loop forever. Fixed by adding a hard `max_pages` cap.

2. **A schema design flaw only a real database could catch.** `raw_records.run_id` was modeled as a strict foreign key to `job_runs.id`. The moment tests ran against real Postgres — the point of the no-SQLite-fallback decision — every sink test that didn't first create a matching `JobRun` row failed with a foreign-key violation. This wasn't just a test-setup gap: a hard FK there means you could never prune old run history without cascading into deleted ingested data. Fixed by dropping the FK.

3. **The most serious one: pagination was silently broken against the real API, and every mocked test stayed green throughout.** After bringing up docker-compose and triggering a real ingestion run, `GET /runs` showed `pages_fetched` climbing past 100, 200, 400+, against an API that only has 42 pages. Root cause: `httpx` silently strips a URL's own embedded query string when `params={}` is passed explicitly (`params=None` leaves it alone), and the Fetcher was passing `params=authed.params` where `RequestSpec.params` defaulted to `{}` whenever a pagination strategy didn't need to add params of its own — exactly the case for the two pagination styles whose "next" URL already carries its own query string. Every "next page" request was silently collapsing back to page 1 and re-fetching it forever. This was invisible to all 19 tests passing at the time, because respx's default route matching ignores query strings, so a mock matched regardless of which URL variant was actually requested. It was only caught by watching a live run against the real API and noticing the record count didn't match the API's known total. Fixed at the single Fetcher call site (`params=authed.params or None`), with a regression test added that asserts on the actual outgoing request URL rather than trusting a query-agnostic mock match.

That third case is the clearest argument in this build for why the brief requires demoing against real APIs rather than stopping at mocked tests: the feature was completely broken, with full test coverage green, until I actually watched a real run.

4. **The test suite itself destroyed live demo data.** `tests/conftest.py`'s DB fixture called `Base.metadata.drop_all()` in teardown after every test. Running the full suite with `DATABASE_URL` pointed at the same compose Postgres that was serving the just-verified live demo silently wiped `job_runs`/`raw_records` — the exact evidence gathered a few steps earlier. Caught by registering a runtime source afterward and getting an unhandled 500 (`relation "job_runs" does not exist`) instead of a normal ingest. Fixed by dropping the `drop_all()` call — `create_all` is idempotent and every test already uses a distinct `source_id`, so a clean slate was never actually needed, and a test fixture should never be able to destroy data in whatever Postgres instance it happens to be pointed at.
