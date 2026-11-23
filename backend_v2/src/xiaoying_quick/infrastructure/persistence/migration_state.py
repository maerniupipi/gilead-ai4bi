"""Read-only Alembic revision inspection used by startup and readiness."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import Engine


class SchemaNotCurrentError(RuntimeError):
    """Raised before serving when a migration-managed database is not at head."""


@dataclass(frozen=True)
class MigrationState:
    current_heads: tuple[str, ...]
    expected_heads: tuple[str, ...]

    @property
    def is_current(self) -> bool:
        return bool(self.expected_heads) and set(self.current_heads) == set(self.expected_heads)


def migration_script_location() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def expected_migration_heads() -> tuple[str, ...]:
    scripts = ScriptDirectory(str(migration_script_location()))
    return tuple(sorted(scripts.get_heads()))


def inspect_migration_state(engine: Engine) -> MigrationState:
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        current_heads = tuple(sorted(context.get_current_heads()))
    return MigrationState(
        current_heads=current_heads,
        expected_heads=expected_migration_heads(),
    )


def assert_database_at_head(engine: Engine) -> None:
    state = inspect_migration_state(engine)
    if state.is_current:
        return
    current = ",".join(state.current_heads) if state.current_heads else "unversioned"
    expected = ",".join(state.expected_heads) if state.expected_heads else "no_migrations"
    raise SchemaNotCurrentError(
        f"application database schema is not current (current={current}, expected={expected})"
    )
