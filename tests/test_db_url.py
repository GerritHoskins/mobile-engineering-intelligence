from app.db import DEFAULT_DATABASE_URL, database_url


def test_database_url_env_var_wins_over_parts() -> None:
    env = {"DATABASE_URL": "postgresql+psycopg://a:b@h:1/d", "DB_HOST": "ignored"}
    assert database_url(env) == "postgresql+psycopg://a:b@h:1/d"


def test_composes_url_from_parts_and_quotes_special_characters() -> None:
    env = {
        "DB_HOST": "db.example.internal",
        "DB_PORT": "5433",
        "DB_NAME": "mei",
        "DB_USER": "mei",
        "DB_PASSWORD": "p@ss:w/rd%#?",
    }
    assert database_url(env) == (
        "postgresql+psycopg://mei:p%40ss%3Aw%2Frd%25%23%3F@db.example.internal:5433/mei"
    )


def test_composed_url_defaults_port_and_name() -> None:
    env = {"DB_HOST": "h", "DB_USER": "u", "DB_PASSWORD": "p"}
    assert database_url(env) == "postgresql+psycopg://u:p@h:5432/mei"


def test_falls_back_to_local_default() -> None:
    assert database_url({}) == DEFAULT_DATABASE_URL


def test_quoted_password_survives_alembic_config_interpolation() -> None:
    # alembic/env.py escapes "%" because Config is a configparser: every
    # URL-quoted RDS password contains "%", and unescaped it would either
    # raise or be silently mangled by interpolation.
    from alembic.config import Config

    url = database_url(
        {"DB_HOST": "h", "DB_USER": "mei", "DB_PASSWORD": "p@ss%w/rd", "DB_NAME": "mei"}
    )
    assert "%" in url

    config = Config()
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))

    assert config.get_main_option("sqlalchemy.url") == url
    assert config.get_section(config.config_ini_section)["sqlalchemy.url"] == url
