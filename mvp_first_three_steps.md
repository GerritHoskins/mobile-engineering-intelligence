# First 3 Build Steps — Mobile Engineering Intelligence MVP

## Context

The `mobile-engineering-intelligence` workspace is currently empty except `AGENTS.md`, which designates this repository (`context-vault`) as read-only canonical architecture/design context for this project. That vault contains a three-times reviewed MVP plan (`mvp_plan.md`) for a **State Reconciliation Engine**: given independently-scoped observations about a mobile installation's push-notification state (user intent, OS capability, provider registration), deterministically derive an effective deliverable state and explain any genuine inconsistencies — without conflating legitimate intent/capability differences with actual bugs.

This plan covers only the first 3 of that spec's 6 Build Steps — enough to have a working project skeleton, a defined (but not yet applied) database schema, and the core reconciliation logic fully tested. Steps 4–6 (seed data, API wiring, end-to-end docker verification) are follow-on work.

**Known constraint:** the target machine has no Docker/Podman/colima and no local Postgres binary at planning time. The Alembic migration will be written but not run/verified in this pass — that happens once container tooling (or a local Postgres) is available.

**Known naming discrepancy:** `mvp_plan.md`'s Project Structure section names the root `mobile-eng-intelligence/`; this plan builds directly in the actual workspace root (`mobile-engineering-intelligence/`) instead, per `AGENTS.md`'s instruction to flag doc/workspace conflicts rather than silently follow one.

## Step 1 — Scaffold the project

- `uv init` in the workspace root (package mode, Python 3.13).
- Add dependencies via `uv add`: `fastapi`, `sqlalchemy>=2`, `alembic`, `pydantic`, `psycopg[binary]` (plain sync driver, matching the vault's SQLAlchemy 2.x sync style and keeping step 3 simple).
- Add dev dependencies via `uv add --dev`: `pytest`.
- Create `compose.yaml` with two services only — `api` and `postgres` — matching the vault spec (no redis/worker/queue/frontend). `api` build context is the project root; `postgres` uses an official `postgres:16` image with a named volume.
- Create the directory skeleton from the vault's Project Structure:
  ```
  app/
    main.py
    db.py
    models.py
    reconciliation/
    api/
    seed.py
  alembic/
    versions/
  tests/
  ```
  `main.py`, `db.py`, `api/state.py`, `seed.py` get minimal placeholder content for now (step 1 is scaffolding, not full wiring — that's step 5/6 of the full plan, out of scope here).

## Step 2 — Define the `state_observation` schema (Alembic, not yet applied)

- `alembic init alembic`, then point `alembic.ini` / `env.py` at `app.db` for the SQLAlchemy URL (env-var driven, e.g. `DATABASE_URL`, so it isn't hardcoded).
- Define `StateObservation` in `app/models.py` (SQLAlchemy 2.x declarative) matching the vault's locked schema exactly:
  - `id` (UUID, server default `gen_random_uuid()`)
  - `subject_type`, `subject_id` (TEXT, not null)
  - `subject_metadata` (JSONB, default `{}`)
  - `domain`, `source`, `key` (TEXT, not null)
  - `value` (JSONB, not null)
  - `observed_at` (TIMESTAMPTZ, not null)
  - `metadata` (JSONB, default `{}`)
  - index on `(subject_type, subject_id, domain)`
- Generate the Alembic migration (`alembic revision --autogenerate -m "create state_observation"`) and hand-check the generated DDL against the vault's `CREATE TABLE` block.
- **Not done in this step:** running `alembic upgrade head`, wiring it into `compose.yaml`'s startup sequence, or standing up Postgres to verify it. That's deferred until container tooling is available — flag it as an open item when this step is reported done.

## Step 3 — Implement `evaluate_push_state` test-first

This is the correctness-critical part the vault plan says deserves nearly all the design effort, and it needs no database at all — pure Python, unit-testable in isolation.

- In `app/reconciliation/push_state.py`, implement the models and function from the vault spec:
  - `Evidence`, `ConsistencyIssue`, `PushEvaluation` (Pydantic models)
  - `evaluate_push_state(observations: list[StateObservation]) -> PushEvaluation`, implementing the exact 3-step precedence algorithm from `mvp_plan.md`:
    1. Intent short-circuit (`desired == DISABLED` → `deliverable=False`, no issues)
    2. Collect *all* applicable issues independently (not first-match): `OS_PERMISSION_BLOCKS_PUSH`, `PROVIDER_REGISTRATION_MISSING`, `BACKEND_PROVIDER_STATE_DIVERGED`, `PROVIDER_REGISTRATION_STALE`
    3. Deliverable precedence `FALSE > UNKNOWN > TRUE`
  - A `normalize()` helper enforcing the value-normalization boundary (raw values → canonical `ENABLED/DISABLED/UNKNOWN`, `ALLOWED/DENIED/UNKNOWN`, `REGISTERED/NOT_REGISTERED/MISSING/STALE`; unrecognized raw tokens raise).
- In `tests/test_push_state_reconciliation.py`, encode all 13 seed scenarios (A–M) from the vault's table as parametrized pytest cases, asserting on `desired_state`, `capability_state`, `registration_state`, `effective_state.deliverable`, and `consistency_issues[].code/severity/remediation`.
  - Cases K, L, M specifically assert the overlap-precedence behavior (DISABLED suppresses a genuine stale-registration issue; a known blocker outranks unknown intent; two genuinely coexisting issues are both collected).
  - **Clarified contract:** Cases F and G should expect `consistency_issues=[]` despite non-final states (`UNKNOWN`) unless an explicit issue condition is met.
  - A generic assertion across all cases with non-empty `consistency_issues`: every entry has `code`, `severity`, `remediation`, and non-empty `evidence`.
- Run `uv run pytest` and confirm all 13+ scenario tests (plus the completeness assertion) pass.

## Verification

- `uv run pytest -v` — all reconciliation tests green, including the K/L/M overlap cases and the finding-completeness assertion.
- `uv run python -c "import app.models"` and `uv run alembic check` (or equivalent) — migration file is syntactically valid and matches the model, even though it isn't applied against a live Postgres yet.
- Manually diff the generated migration's DDL against the vault's `CREATE TABLE state_observation` block to confirm no drift.
- Explicitly report as an open item: DB not stood up, so the migration is unverified against a real Postgres instance — to be closed once Docker/colima or local Postgres is installed (steps 4–6 of the full plan depend on this).
