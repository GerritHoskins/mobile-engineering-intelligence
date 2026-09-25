# Mobile Engineering Intelligence

A backend service that answers two questions about a mobile app, without guessing:

1. **Is this subject's state consistent?** For example, can this installation actually receive push notifications, and does this account's profile agree across every system that holds a copy?
2. **What changed before this crash?** For a Sentry issue, which release introduced it, which commits and Jira tickets shipped in that release, and which commits touched the files in the stack trace?

The rule behind both: when the evidence is missing or ambiguous, the answer is `UNKNOWN` with a finding explaining why. It is never quietly turned into "fine" or "no suspects".

Stack: Python 3.13, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16, managed with [uv](https://docs.astral.sh/uv/).

## Contents

- [How it works](#how-it-works)
- [API](#api)
- [Local development](#local-development)
- [Ingesting real data](#ingesting-real-data)
- [Deployment](#deployment)
- [Repository layout](#repository-layout)
- [Design notes](#design-notes)

## How it works

### State reconciliation (`/v1/state`)

Systems report facts about a subject as rows in one generic table, `state_observation`: `(subject_type, subject_id, domain, source, key, value, observed_at)`. At query time the API keeps only the newest row for each `(source, key)`. That filtering runs in SQL with `ROW_NUMBER() OVER (...)`, not in Python. The remaining rows are then evaluated by that domain's reconciliation logic.

Two domains share the same table with no schema changes between them:

| Domain | Subject type | What it evaluates |
|---|---|---|
| `push` | `installation` | *Combines* three independent signals: backend intent (`push_enabled`), OS capability (`os_permission`) and provider registration (Braze). Produces `effective_state.deliverable` as `true`, `false` or `null`, with precedence `false > unknown > true`. |
| `profile` | `account` | *Compares* copies of the same fact against the field's authoritative source: `email` from `auth`, `postal_code` from `backend`. Produces `effective_state.consistent`. |

Raw values are normalized when they are loaded, and unrecognized tokens are rejected rather than coerced. For example, a postal code stored as the JSON number `1067` has already lost the leading zero of `"01067"`, so it is rejected. Staleness is judged against wall-clock time.

Consistency issue codes:

| Domain | Codes |
|---|---|
| `push` | `OS_PERMISSION_BLOCKS_PUSH`, `PROVIDER_REGISTRATION_MISSING`, `PROVIDER_REGISTRATION_STALE`, `BACKEND_PROVIDER_STATE_DIVERGED` |
| `profile` | `PROFILE_FIELD_DIVERGED`, `PROFILE_FIELD_MISSING`, `PROFILE_FIELD_SYNC_PENDING` |

### Incident context (`/v1/incidents`)

`python -m app.ingest` pulls three kinds of data into dedicated tables: GitHub tags and commits, the Jira tickets those commits reference, and Sentry issues, events and session counts. `app/incidents/context.py` then walks this chain:

**Sentry issue → first release → git tag → commits since the previous tag → changed files + tickets → suspect commits**

A commit is a suspect when it changed a file that appears in the incident's stack trace. Suspects are ranked by how close the matching frame is to the crash. `suspects` is `"UNKNOWN"`, never `[]`, when:

- the first release has no git tag (`RELEASE_NOT_FOUND`),
- it is the first tagged release, so there is nothing to diff against (`NO_PREVIOUS_RELEASE`),
- no stack frame maps to a repo path, e.g. a minified bundle without source maps (`FRAMES_UNMAPPABLE`).

Other findings: `NO_SUSPECT_COMMIT`, `SUSPECT_WITHOUT_TICKET`.

Everything specific to one organization lives in `config/org.<name>.yaml`: repo, Jira project and ticket-key pattern, Sentry org and project, release/tag naming templates, path-to-component globs, and frame-path rewriting. Pointing the service at another org means adding a config file, not changing code. `config/org.demo.yaml` targets the personal demo accounts.

## API

Interactive docs are served at `/docs` while the app is running.

### `GET /v1/state/{subject_type}/{subject_id}?domain=push|profile`

- `domain` defaults to `push`.
- `400` for an unknown `subject_type` or `domain`, or when they don't match (`push` requires `installation`, `profile` requires `account`).
- A subject with no observations returns `200` with every state `UNKNOWN`, `deliverable`/`consistent` set to `null`, and `consistency_issues: []`. It does not return `404`, because nothing records which subjects exist, so "doesn't exist" and "hasn't reported yet" look the same.

```console
$ curl -s localhost:8000/v1/state/installation/install-case-c | jq
{
  "subject": { "type": "installation", "id": "install-case-c" },
  "domain": "push",
  "desired_state": { "push_enabled": "ENABLED" },
  "capability_state": { "os_permission": "DENIED" },
  "registration_state": { "provider_registration": "REGISTERED" },
  "effective_state": { "deliverable": false },
  "consistency_issues": [ { "code": "OS_PERMISSION_BLOCKS_PUSH", ... } ]
}
```

### `GET /v1/incidents/{sentry_issue_id}/context?org=demo`

- `org` defaults to `demo`. An `org` with no matching `config/org.<org>.yaml` returns `400`.
- `404` if that Sentry issue hasn't been ingested for the org. An incident is a concrete ingested record, unlike a state subject.
- Returns `incident`, `release`, `commits`, `tickets`, `suspects` (a list or `"UNKNOWN"`) and `findings`.

## Local development

Prerequisites: [uv](https://docs.astral.sh/uv/getting-started/installation/) and either Docker or a local PostgreSQL 16.

### Option A: Docker Compose

```sh
docker compose up --build
```

This starts Postgres plus the API on `localhost:8000`. The container runs `alembic upgrade head` before `uvicorn` starts (`scripts/start.sh`).

### Option B: local Postgres

```sh
uv sync

# One role, two databases: `mei` for dev, `mei_test` for pytest.
psql -U postgres -c "CREATE ROLE mei WITH LOGIN PASSWORD 'mei';"
createdb -U postgres -O mei mei
createdb -U postgres -O mei mei_test

uv run alembic upgrade head               # dev DB (DATABASE_URL defaults to .../mei)
uv run uvicorn app.main:app --reload
```

The connection comes from `DATABASE_URL`, which defaults to `postgresql+psycopg://mei:mei@localhost:5432/mei`. On ECS it is assembled from `DB_HOST`, `DB_USER` and `DB_PASSWORD` (optionally `DB_PORT` and `DB_NAME`) instead; see `app/db.py`.

### Seed data and end-to-end check

```sh
uv run python -m app.seed               # 13 push installations (A–M) + 10 profile accounts (P1–P10)
bash scripts/verify_seed_scenarios.sh   # curl + jq sweep against the running API; needs jq
```

The seed is idempotent: it deletes and re-inserts only its own fixed subject IDs, so re-running it produces identical rows. Seeded timestamps are fixed. Because staleness is judged against wall-clock time, "fresh" seed rows will eventually read as stale. That is expected.

### Tests

```sh
uv run pytest
```

The API and ingestion tests run against a real Postgres database, `mei_test`, not mocks. A session fixture migrates the database to `head`, and each test truncates the tables it uses. `tests/conftest.py` points `DATABASE_URL` at `mei_test` unless you set it yourself. The reconciliation and incident-context logic tests are pure and need no database.

### Schema changes

Alembic owns the schema. The app never calls `create_all`.

```sh
uv run alembic revision --autogenerate -m "describe the change"
uv run alembic upgrade head
```

## Ingesting real data

Copy `.env.example` to `.env` and fill in the read tokens. `.env` is gitignored, and tokens are only read from the environment.

```sh
uv run python -m app.ingest --org demo --days 14    # GitHub + Jira + Sentry -> Postgres
```

Ingestion is read-only towards GitHub, Jira and Sentry. Every write is a Postgres upsert on the table's primary key, so re-runs are idempotent. `--days` sets the Sentry lookback window.

Supporting tools:

- `uv run python -m app.connectors.record --org demo` runs a normal ingest through a recording transport and saves scrubbed vendor responses under `tests/fixtures/vendors/<org>/` for replay in tests. No recordings are committed yet; the current ingestion tests use fake connectors built from `scripts/demo/scenario.py`.
- `uv run python -m scripts.demo.generate {jira|git|sentry-events|sentry-sessions} [--dry-run]` plants the demo scenario in the personal demo accounts. These commands **write** to external services. Use `--dry-run` first.

## Deployment

There is one AWS dev environment (`eu-central-1`), defined with Terraform under `infra/`:

| Path | Purpose |
|---|---|
| `infra/bootstrap/` | Applied once, with local state. Creates the S3 bucket for Terraform state and a monthly budget alert. |
| `infra/envs/dev/` | The environment. VPC with public and private subnets, RDS Postgres in the private subnets, and ECS Fargate behind an ALB with an HTTP listener. |
| `infra/modules/` | `network`, `database`, `service` (ECR, ALB, ECS, IAM, logs) and `github_oidc` (the image-push role). |

```sh
cd infra/envs/dev
cp backend.hcl.example backend.hcl && cp terraform.tfvars.example terraform.tfvars   # both gitignored; fill in
terraform init -backend-config=backend.hcl
terraform apply
```

The RDS-managed password reaches the task as its own secret. `app/db.py` URL-quotes it when building the connection string, because it may contain characters like `@` or `/`.

**CI:** `.github/workflows/image.yml` builds the Docker image and pushes it to ECR, tagged with the commit SHA. It runs on pushes to `main` that touch app, config, migration or image files, and can also be triggered manually. It authenticates to AWS through GitHub OIDC, so no AWS keys are stored in the repo. The job is skipped until the repo variables `AWS_ROLE_ARN` and `ECR_REPOSITORY` (optionally `AWS_REGION`) are set. There is no CI test job yet; run `uv run pytest` locally before pushing.

## Repository layout

```
app/
  main.py                 FastAPI app; mounts the state and incident routers
  db.py                   engine/session, DATABASE_URL or DB_* resolution
  models.py               SQLAlchemy models (state_observation + incident-context tables)
  api/                    HTTP layer: state.py, incidents.py
  reconciliation/         pure domain logic: push_state.py, profile_state.py, common.py
  incidents/              pure incident-context logic, event normalization, DB loading
  connectors/             read-only GitHub / Jira / Sentry clients + recording transport
  ingest.py               CLI: vendor data -> Postgres (upserts)
  orgs.py                 typed loader for config/org.<name>.yaml
  seed.py                 deterministic A–M / P1–P10 fixtures
alembic/                  migrations (Alembic owns the schema)
config/                   per-org configuration (no secrets)
scripts/
  start.sh                container entrypoint: migrate, then serve
  verify_seed_scenarios.sh
  demo/                   demo-data scenario + generator (writes to external accounts)
infra/                    Terraform: bootstrap, envs/dev, modules
tests/                    pytest; API/ingest tests use a real mei_test Postgres
```

## Design notes

- **UNKNOWN is a first-class answer.** No observations, stale data, unmappable frames and untagged releases each produce `UNKNOWN` and an explanatory finding. A confident "all good" would be wrong.
- **Pure logic, thin edges.** `app/reconciliation/` and `app/incidents/context.py` do no I/O and are tested directly. The API modules only load data and serialize the result.
- **One generic observation table.** New state domains are additions to `DOMAINS` in `app/api/state.py` plus a reconciliation module. No new tables.
- **Org-specific values are config.** Nothing about a particular GitHub repo, Jira project or Sentry org is hard-coded.
- **Architecture context** (ADRs, the MVP plan, the A–M and P1–P10 scenario tables) lives in the separate `context-vault` repository. `AGENTS.md` and `CLAUDE.md` describe how to use it. The `mvp_*.md` files in this repo are working notes from the MVP build steps.
