from fastapi import FastAPI

from app.api import state

app = FastAPI(title="Mobile Engineering Intelligence")
app.include_router(state.router)
