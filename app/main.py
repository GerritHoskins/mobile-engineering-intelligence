from fastapi import Depends, FastAPI
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import incidents, releases, state
from app.db import engine, get_session
from app.observability import add_request_logging, setup_tracing

app = FastAPI(title="Mobile Engineering Intelligence")
app.include_router(state.router)
app.include_router(incidents.router)
app.include_router(releases.router)
add_request_logging(app)
setup_tracing(app, engine)


@app.get("/healthz")
def healthz(session: Session = Depends(get_session)) -> dict:
    """Liveness plus database reachability, for the load balancer."""
    session.execute(text("SELECT 1"))
    return {"status": "ok"}
