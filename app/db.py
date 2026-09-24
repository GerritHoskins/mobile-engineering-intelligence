import os
from collections.abc import Iterator, Mapping
from urllib.parse import quote

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql+psycopg://mei:mei@localhost:5432/mei"


def database_url(env: Mapping[str, str] = os.environ) -> str:
    """DATABASE_URL wins (local dev, tests, compose). Otherwise build it from
    DB_* parts -- on ECS the RDS-managed password is injected as its own
    secret and may contain URL-special characters, so it is quoted here."""
    if url := env.get("DATABASE_URL"):
        return url
    if host := env.get("DB_HOST"):
        user = quote(env["DB_USER"], safe="")
        password = quote(env["DB_PASSWORD"], safe="")
        port = env.get("DB_PORT", "5432")
        name = env.get("DB_NAME", "mei")
        return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{name}"
    return DEFAULT_DATABASE_URL


DATABASE_URL = database_url()

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)


class Base(DeclarativeBase):
    pass


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
