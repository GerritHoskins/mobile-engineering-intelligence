# Build Steps 4–6 — Mobile Engineering Intelligence MVP

## Context

Build steps 1–3 of the vault's `mvp_plan.md` (scaffold, `state_observation` schema, `evaluate_push_state` test-first) are done and committed (`819ca4d "Scaffolding Steps 1-3"`, pushed to `git@github.com:GerritHoskins/mobile-engineering-intelligence.git`, branch `main`). 33 pytest cases pass for the reconciliation logic. The Alembic migration exists but has never been applied — this workspace had no Docker/Podman/colima and no local Postgres.

This plan covers the remaining three build steps: `seed.py` (step 4), wiring the `GET /v1/state/{subject_type}/{subject_id}` endpoint (step 5), and end-to-end verification (step 6). Unlike steps 1–3, these steps are only meaningful if actually run against a real database — seeding idempotency and API responses can't be verified by reading code.

**Tooling decision (this pass):** install Postgres locally via Homebrew (`postgresql@16`) rather than installing Docker/colima. `compose.yaml` (already written) stays as the eventual containerized-deployment path but is **not used** for this pass — local dev/verification runs `uv run uvicorn` directly against a Homebrew-managed Postgres. This is a deviation from the vault's literal "`docker compose up`" instruction in step 6, to be flagged in the vault update afterward, same as the step 1–3 deviations already recorded there.

**Small hygiene item folded in:** the current repo has no `.gitignore` and 12 `__pycache__/*.pyc` files got committed in the steps 1–3 commit. Adding a `.gitignore` and untracking those is a two-command fix, bundled in since it's the same repo and trivial — not a separate task.

## Step 0 — Local Postgres setup (prerequisite for steps 4–6)

- `brew install postgresql@16`, start it as a background service (`brew services start postgresql@16`).
- Create a dedicated role and two databases matching the `compose.yaml` credential shape (`mei`/`mei`), so `DATABASE_URL` stays consistent between local dev and the eventual container path:
  - `createuser mei --pwprompt` (or `psql` `CREATE ROLE`), `createdb -O mei mei` (dev), `createdb -O mei mei_test` (test).
- `DATABASE_URL=postgresql+psycopg://mei:mei@localhost:5432/mei uv run alembic upgrade head` — apply the existing `27c47fa8f0b4_create_state_observation` migration for real, against the dev DB. Repeat against `mei_test` for the test DB (a pytest fixture will do this automatically for CI-style runs — see Step 5).
- This closes the "migration never applied" open item from `mvp_plan_revisions.md`'s 2026-09-13 implementation-confirmation pass.

## Step 4 — `seed.py`: deterministic, idempotent fixtures for scenarios A–M

- In `app/seed.py`, insert `StateObservation` rows for 13 fixed installations (`install-case-a` … `install-case-m`), one set of `(backend.enabled, os.permission, braze.registration)` observations per the vault's A–M table (same values already encoded as test fixtures in `tests/test_push_state_reconciliation.py` — reuse that table as the source of truth so seed data and tests can't drift apart).
- **Fixed timestamps, not `utcnow()`:** a module-level `SEED_REFERENCE_TIME` constant (e.g. `2026-09-13T00:00:00Z`) anchors "fresh" (`SEED_REFERENCE_TIME - 1 day`) and "stale" (`SEED_REFERENCE_TIME - 45 days`) observed_at values, matching the same fixed-`NOW` pattern already used in the reconciliation tests. Flag as a known limitation: since `evaluate_push_state`'s staleness check compares against real wall-clock time at query time (not `SEED_REFERENCE_TIME`), the "fresh" cases will themselves read as stale once enough real time passes after seeding — acceptable for an MVP demo, not a bug in the reconciliation logic itself.
- **Idempotency strategy:** the locked `state_observation` schema (from step 2) has no unique constraint on `(subject_type, subject_id, domain, source, key)`, so a Postgres `ON CONFLICT` upsert isn't available without an unplanned schema change. Instead, `seed.py` deletes any existing rows for each of the 13 fixed `subject_id`s before inserting the fresh set, all per-subject in one transaction — functionally idempotent (re-running produces identical rows) without touching the already-locked schema. This choice will be called out explicitly in the vault update as an interpretation of "upserted rather than inserted."
- `seed.py` takes `DATABASE_URL` from the environment (same convention as `app/db.py` and `alembic/env.py`) and is runnable directly: `uv run python -m app.seed`.

## Step 5 — Wire `GET /v1/state/{subject_type}/{subject_id}`

- In `app/api/state.py`, implement the endpoint per the vault's locked API contract:
  - `subject_type` must equal `installation`; anything else → `400`.
  - `domain` query param defaults to `push` (only implemented domain).
  - Load observations for `(subject_type, subject_id, domain)` using the windowed latest-per-key query (`ROW_NUMBER() OVER (PARTITION BY subject_type, subject_id, domain, source, key ORDER BY observed_at DESC) = 1`), expressed via SQLAlchemy Core (`func.row_number()... .over(...)`) against `app.models.StateObservation` — not loaded-then-filtered in Python.
  - Convert loaded rows to `RawObservation` (from `app.reconciliation.push_state`) and call `evaluate_push_state`.
  - Zero observations → `200` with all three states `UNKNOWN`, `effective_state.deliverable=null`, `consistency_issues=[]` (no `404` — there's no `subjects` table to distinguish "doesn't exist" from "hasn't reported yet").
  - Serialize the full response shape from the vault's API section (`subject`, `domain`, `desired_state`, `capability_state`, `registration_state`, `effective_state`, `consistency_issues`).
- Add a DB-session dependency in `app/db.py` (a `get_session` FastAPI dependency wrapping `SessionLocal`) so the endpoint doesn't manage sessions ad hoc.
- New `tests/test_state_api.py` using FastAPI's `TestClient` against the **real `mei_test` Postgres** (not mocked): a session-scoped fixture runs `alembic upgrade head` against `mei_test` once, per the vault's requirement that "local/manual verification and pytest can't silently drift apart." Assert:
  - `subject_type != installation` → `400`.
  - Omitted `domain` defaults to `push`.
  - Empty-observation subject → `200` with the UNKNOWN/`null` contract.
  - At least one seeded-style subject (e.g. re-using scenario C's observations) returns the expected `consistency_issues`.

## Step 6 — End-to-end local verification

- `uv run uvicorn app.main:app --reload` against the dev DB (`mei`).
- `uv run python -m app.seed` to populate the 13 installations.
- `curl localhost:8000/v1/state/installation/install-case-a` through `install-case-m`, diff each response against the vault's A–M table (including the corrected F/G "none" entries from the last vault update).
- Re-run `uv run python -m app.seed` a second time; confirm row counts and API responses are unchanged (idempotency check).
- `uv run pytest -v` (now includes `test_state_api.py` against `mei_test` alongside the existing reconciliation tests).

## Hygiene fix (bundled)

- Add a `.gitignore` covering `.venv/`, `__pycache__/`, `*.pyc`, `.DS_Store`, `.pytest_cache/`.
- `git rm -r --cached` the 12 already-tracked `__pycache__`/`.pyc` paths (working tree files are untouched, just untracked from git).

## After implementation: update context-vault

Once steps 4–6 are verified, update the same three vault docs as last time (`mvp_first_three_steps.md`, `mvp_plan.md`, `mvp_plan_revisions.md`), following the established pattern: mark steps `[DONE]` with implementation notes, and explicitly call out the two deviations — (a) local Homebrew Postgres used for dev/verification instead of `docker compose up` (compose.yaml itself is unchanged and still valid for a future containerized pass), and (b) the delete-then-insert idempotency strategy in `seed.py` in place of a Postgres `ON CONFLICT` upsert, since no unique constraint exists on the locked schema.

## Verification

- `uv run alembic upgrade head` succeeds against both `mei` and `mei_test` with no errors.
- `uv run pytest -v` — all reconciliation tests (33, unchanged) plus the new `test_state_api.py` cases pass.
- Manual curl sweep over all 13 installations matches the vault's A–M table exactly (including corrected F/G).
- Second `seed.py` run produces no duplicate rows and identical API output (idempotency).
- `git status` clean after the `.gitignore`/untracking fix, with no `.pyc` files reappearing on a subsequent `pytest` run.
