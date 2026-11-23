"""Safe, passive readiness probes backed by the application database."""

from __future__ import annotations

from sqlalchemy import Engine, func, inspect, select, text
from sqlalchemy.exc import SQLAlchemyError

from xiaoying_quick.infrastructure.persistence.base import Base
from xiaoying_quick.infrastructure.persistence.migration_state import (
    inspect_migration_state,
)
from xiaoying_quick.infrastructure.persistence.models.data_sources import (
    DataSourceModel,
    DomainBindingModel,
)
from xiaoying_quick.modules.health import DependencyCheck, DependencyStatus


class SqlAlchemyDependencyProbe:
    """Probe the control database and report external dependency configuration.

    The Lab is never called and business databases are never connected here.
    Business-source state comes only from the application's own control tables.
    """

    def __init__(
        self,
        engine: Engine,
        *,
        migration_managed: bool,
        lab_configured: bool,
    ) -> None:
        self._engine = engine
        self._migration_managed = migration_managed
        self._lab_configured = lab_configured

    def check(self) -> tuple[DependencyCheck, ...]:
        database = self._application_database_check()
        if database.status is not DependencyStatus.OK:
            return (
                database,
                self._schema_unknown(),
                self._lab_check(),
                self._business_sources_unknown(),
            )

        schema = self._schema_check()
        sources = (
            self._business_sources_check()
            if schema.status is DependencyStatus.OK
            else self._business_sources_unknown()
        )
        return (database, schema, self._lab_check(), sources)

    def _application_database_check(self) -> DependencyCheck:
        try:
            with self._engine.connect() as connection:
                connection.execute(text("SELECT 1")).scalar_one()
        except SQLAlchemyError:
            return DependencyCheck(
                name="application_database",
                status=DependencyStatus.ERROR,
                critical=True,
                mode="connectivity",
                detail="unreachable",
            )
        return DependencyCheck(
            name="application_database",
            status=DependencyStatus.OK,
            critical=True,
            mode="connectivity",
            detail="reachable",
        )

    def _schema_check(self) -> DependencyCheck:
        try:
            if self._migration_managed:
                current = inspect_migration_state(self._engine).is_current
            else:
                actual_tables = set(inspect(self._engine).get_table_names())
                current = set(Base.metadata.tables).issubset(actual_tables)
        except Exception:
            # Invalid/missing migration bundles are also a not-ready schema,
            # but their internal path and parser errors must not be exposed.
            current = False
        return DependencyCheck(
            name="application_schema",
            status=DependencyStatus.OK if current else DependencyStatus.ERROR,
            critical=True,
            mode="migration_revision" if self._migration_managed else "metadata_presence",
            detail="current" if current else "not_current",
        )

    def _lab_check(self) -> DependencyCheck:
        return DependencyCheck(
            name="laboratory",
            status=(
                DependencyStatus.CONFIGURED
                if self._lab_configured
                else DependencyStatus.NOT_CONFIGURED
            ),
            critical=False,
            mode="passive_configuration",
            detail="network_probe_disabled",
        )

    def _business_sources_check(self) -> DependencyCheck:
        try:
            with self._engine.connect() as connection:
                active_count = connection.execute(
                    select(func.count())
                    .select_from(DomainBindingModel)
                    .join(
                        DataSourceModel,
                        DataSourceModel.id == DomainBindingModel.data_source_id,
                    )
                    .where(
                        DomainBindingModel.active.is_(True),
                        DataSourceModel.state == "active",
                    )
                ).scalar_one()
        except SQLAlchemyError:
            return self._business_sources_unknown()
        return DependencyCheck(
            name="business_data_sources",
            status=(
                DependencyStatus.CONFIGURED if active_count > 0 else DependencyStatus.NOT_CONFIGURED
            ),
            critical=False,
            mode="control_metadata_only",
            detail="active_bindings_present" if active_count > 0 else "no_active_bindings",
        )

    @staticmethod
    def _schema_unknown() -> DependencyCheck:
        return DependencyCheck(
            name="application_schema",
            status=DependencyStatus.UNKNOWN,
            critical=True,
            mode="migration_revision",
            detail="database_unavailable",
        )

    @staticmethod
    def _business_sources_unknown() -> DependencyCheck:
        return DependencyCheck(
            name="business_data_sources",
            status=DependencyStatus.UNKNOWN,
            critical=False,
            mode="control_metadata_only",
            detail="not_checked",
        )
