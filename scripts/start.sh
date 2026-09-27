#!/usr/bin/env sh
# Container startup: apply migrations, then serve. Per mvp_plan.md build step 2,
# the app never relies on Base.metadata.create_all — Alembic owns the schema.
# DATABASE_URL is read by both alembic/env.py and app/db.py.
set -eu

alembic upgrade head
# No uvicorn access log: request paths carry installation/account/issue ids.
# app.observability logs the route template, status and latency instead.
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8000}" --no-access-log
