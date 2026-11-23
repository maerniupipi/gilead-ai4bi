"""Seed the documented UAT data source and four Lab domain bindings."""

from __future__ import annotations

import os
from dataclasses import dataclass

from xiaoying_quick.modules.data_sources.contracts import (
    DataSourceDialect,
    DataSourceDraft,
    DataSourceRecord,
    DataSourceSslMode,
)
from xiaoying_quick.modules.data_sources.service import DataSourceService
from xiaoying_quick.modules.identity.contracts import UserRecord
from xiaoying_quick.modules.identity.service import IdentityService
from xiaoying_quick.shared.errors import Conflict

UAT_SOURCE_NAME = "AI_CVRM 实验室查数库"
UAT_SOURCE_URL = os.environ.get("GILEAD_UAT_SOURCE_URL", "mysql+pymysql://db.example:3306")
UAT_SOURCE_USERNAME = os.environ.get("GILEAD_UAT_SOURCE_USERNAME", "gilead_lab_reader")
UAT_SOURCE_PASSWORD = os.environ.get("GILEAD_UAT_SOURCE_PASSWORD", "")
UAT_SOURCE_DATABASE = "AI_CVRM"

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = os.environ.get("GILEAD_UAT_ADMIN_PASSWORD", "")

DOMAIN_TABLES: dict[str, tuple[str, ...]] = {
    "actual": (
        "tw_performance_sales_cvh",
        "tw_target_cvh",
        "td_inst_mkt_decile",
    ),
    "demand": (
        "tw_demand_sales_cvh_org",
        "tw_demand_target_cvh_org",
    ),
    "ext_simple": (
        "td_external_market_ta",
        "td_external_org",
        "td_external_target_ins_level",
        "tw_external_fact_sales",
    ),
    "ext_complex": (
        "td_external_market_ta",
        "td_external_org",
        "td_external_target_ins_level",
        "tw_external_fact_sales",
    ),
}

DOMAIN_JOIN_KEYS: dict[str, tuple[str, ...]] = {
    "actual": (
        "tw_performance_sales_cvh.decile_key=td_inst_mkt_decile.decile_key",
        "tw_target_cvh.decile_key=td_inst_mkt_decile.decile_key",
    ),
    "demand": (
        "tw_demand_sales_cvh_org.org_key=tw_demand_target_cvh_org.org_key",
        "tw_demand_sales_cvh_org.brand_code=tw_demand_target_cvh_org.brand_code",
        "tw_demand_sales_cvh_org.date=tw_demand_target_cvh_org.date",
    ),
    "ext_simple": (
        "tw_external_fact_sales.audit_cod=td_external_org.audit_cod",
        "tw_external_fact_sales.data_source=td_external_org.data_source",
        "tw_external_fact_sales.data_source=td_external_market_ta.data_source",
        "tw_external_fact_sales.data_source=td_external_target_ins_level.data_source",
    ),
    "ext_complex": (
        "tw_external_fact_sales.audit_cod=td_external_org.audit_cod",
        "tw_external_fact_sales.data_source=td_external_org.data_source",
        "tw_external_fact_sales.data_source=td_external_market_ta.data_source",
        "tw_external_fact_sales.data_source=td_external_target_ins_level.data_source",
    ),
}


@dataclass(frozen=True)
class RuntimeBootstrapReport:
    admin_created: bool
    admin_username: str
    data_source_id: str
    data_source_name: str
    data_source_action: str
    revision_id: str
    bindings: tuple[str, ...]
    lab_http_configured: bool

    def to_record(self) -> dict[str, object]:
        return {
            "admin_created": self.admin_created,
            "admin_username": self.admin_username,
            "data_source_id": self.data_source_id,
            "data_source_name": self.data_source_name,
            "data_source_action": self.data_source_action,
            "revision_id": self.revision_id,
            "bindings": list(self.bindings),
            "lab_http_configured": self.lab_http_configured,
        }


def documented_source_objects() -> tuple[str, ...]:
    names: set[str] = set()
    for tables in DOMAIN_TABLES.values():
        names.update(tables)
    return tuple(sorted(names))


def bootstrap_uat_runtime(
    *,
    identity: IdentityService,
    data_sources: DataSourceService,
    actor: UserRecord | None = None,
    lab_http_configured: bool = False,
) -> RuntimeBootstrapReport:
    admin, admin_created = _ensure_admin(identity)
    owner = actor or admin
    source, source_action = _ensure_data_source(data_sources, owner.id)
    revision = data_sources.activate(source.id, owner.id)
    if source_action == "created":
        source_action = "created_and_activated"
    else:
        source_action = "updated_and_activated"
    bindings = _ensure_bindings(data_sources, revision.id, owner.id)
    return RuntimeBootstrapReport(
        admin_created=admin_created,
        admin_username=admin.username,
        data_source_id=source.id,
        data_source_name=source.name,
        data_source_action=source_action,
        revision_id=revision.id,
        bindings=bindings,
        lab_http_configured=lab_http_configured,
    )


def _ensure_admin(identity: IdentityService) -> tuple[UserRecord, bool]:
    try:
        return (
            identity.bootstrap_first_admin(
                username=ADMIN_USERNAME,
                password=ADMIN_PASSWORD,
                display_name=ADMIN_USERNAME,
            ),
            True,
        )
    except Conflict:
        existing = identity.get_by_username(ADMIN_USERNAME)
        if existing is None:
            raise
        return existing, False


def _ensure_data_source(
    data_sources: DataSourceService, actor_id: str
) -> tuple[DataSourceRecord, str]:
    existing = next(
        (item for item in data_sources.list() if item.name == UAT_SOURCE_NAME),
        None,
    )
    draft = DataSourceDraft(
        name=UAT_SOURCE_NAME,
        connection_url=UAT_SOURCE_URL,
        username=UAT_SOURCE_USERNAME,
        password=UAT_SOURCE_PASSWORD,
        selected_database=UAT_SOURCE_DATABASE,
        schema=None,
        dialect=DataSourceDialect.MYSQL,
        ssl_mode=DataSourceSslMode.DISABLE,
        allowed_objects=documented_source_objects(),
        allowed_schemas=(),
        query_timeout_seconds=60,
        max_rows=2000,
        allow_private_network=False,
    )
    if existing is None:
        return data_sources.create(draft, actor_id), "created"
    updated = data_sources.update(existing.id, draft, actor_id)
    return updated, "updated"


def _ensure_bindings(
    data_sources: DataSourceService, revision_id: str, actor_id: str
) -> tuple[str, ...]:
    bound: list[str] = []
    for domain_id, tables in DOMAIN_TABLES.items():
        binding = data_sources.bind_domain(
            domain_id=domain_id,
            lab_id=domain_id,
            revision_id=revision_id,
            actor_id=actor_id,
            allowed_objects=tables,
            allowed_schemas=(),
            allowed_join_keys=DOMAIN_JOIN_KEYS[domain_id],
        )
        bound.append(f"{binding.domain_id}:{binding.id}")
    return tuple(bound)
