"""Request logging without identifiers, and opt-in OpenTelemetry tracing.

uvicorn's access log is switched off (scripts/start.sh) because request paths
carry installation, account and issue ids. This middleware logs the matched
route *template* instead ("/v1/state/{subject_type}/{subject_id}"), so logs
stay useful for rates, errors and latency without holding who was asked about.

Tracing is enabled only when OTEL_EXPORTER_OTLP_ENDPOINT is set (on ECS: the
ADOT collector sidecar, which forwards to X-Ray). Locally and in tests nothing
is instrumented.
"""

import logging
import os
import time

from fastapi import FastAPI, Request
from sqlalchemy.engine import Engine

log = logging.getLogger("app.access")
if not log.handlers:  # uvicorn configures only its own loggers
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False


def route_template(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", None) or "<unmatched>"


def add_request_logging(app: FastAPI) -> None:
    @app.middleware("http")
    async def request_log(request: Request, call_next):
        started = time.perf_counter()
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            log.info("%s %s %d %.0fms", request.method, route_template(request), status,
                     (time.perf_counter() - started) * 1000)


def setup_tracing(app: FastAPI, engine: Engine) -> bool:
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return False
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
    from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    service = os.environ.get("OTEL_SERVICE_NAME", "mobile-engineering-intelligence")
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))  # endpoint from the env var
    trace.set_tracer_provider(provider)
    # Span names use route templates too; query strings are not recorded as attributes.
    FastAPIInstrumentor.instrument_app(app, excluded_urls="healthz")
    SQLAlchemyInstrumentor().instrument(engine=engine)
    HTTPXClientInstrumentor().instrument()
    return True
