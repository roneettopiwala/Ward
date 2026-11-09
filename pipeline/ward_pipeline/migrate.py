"""Apply SQL migrations in api/migrations/ that have not run yet."""

import logging

from sqlalchemy import Engine, text

from .config import MIGRATIONS_DIR

log = logging.getLogger(__name__)


def migrate(eng: Engine) -> None:
    with eng.begin() as conn:
        conn.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "name TEXT PRIMARY KEY, applied_at TIMESTAMPTZ DEFAULT now())"
            )
        )
        done = set(conn.scalars(text("SELECT name FROM schema_migrations")))
        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            if path.name in done:
                continue
            log.info("applying %s", path.name)
            conn.exec_driver_sql(path.read_text())
            conn.execute(text("INSERT INTO schema_migrations (name) VALUES (:n)"), {"n": path.name})
