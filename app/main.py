from fastapi import FastAPI

from app.api import incidents, state

app = FastAPI(title="Mobile Engineering Intelligence")
app.include_router(state.router)
app.include_router(incidents.router)
