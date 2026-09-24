#!/usr/bin/env sh
# Container startup: apply migrations, then serve. Per mvp_plan.md build step 2,
# the app never relies on Base.metadata.create_all — Alembic owns the schema.
# DATABASE_URL is read by both alembic/env.py and app/db.py.
set -eu

alembic upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}"
