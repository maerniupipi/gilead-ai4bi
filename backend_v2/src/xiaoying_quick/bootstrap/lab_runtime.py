"""Pin a run's laboratory connection without storing plaintext credentials."""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy import select
from sqlalchemy.orm import Session

from xiaoying_quick.application.lab_connection import (
    LabConnectionService,
    ResolvedLabConnection,
)
from xiaoying_quick.infrastructure.persistence.models import SourceLabModel
from xiaoying_quick.infrastructure.persistence.repositories.artifacts import (
    SqlAlchemyArtifactRepository,
)
from xiaoying_quick.modules.data_sources.ports import SecretStore
from xiaoying_quick.shared.errors import ValidationFailed

LAB_CONNECTION_SNAPSHOT_KIND = "lab_connection_snapshot"


def resolve_run_lab_connection(
    database: Session,
    app: FastAPI,
    run_id: str | None = None,
) -> ResolvedLabConnection:
    # Import lazily: container composes this helper and owns the app-scoped store.
    from .container import _secret_store, _settings

    settings = _settings(app)
    secrets = _secret_store(app, settings)
    service = LabConnectionService(database, settings, secrets)
    if run_id is None:
        return service.resolve()

    artifacts = SqlAlchemyArtifactRepository(database)
    snapshot = artifacts.latest(run_id=run_id, kind=LAB_CONNECTION_SNAPSHOT_KIND)
    if snapshot is not None:
        if snapshot.get("persisted") is False:
            return _legacy_connection(service, settings)
        return _restore_snapshot(snapshot, secrets, environment=settings.environment)

    connection = service.resolve()
    if connection.persisted:
        snapshot = _snapshot_connection(database, service, connection, secrets)
    else:
        # Keep pre-configuration runs on their original legacy wiring even if
        # the workspace gains an explicit Bootcamp profile before they resume.
        snapshot = {"version": 1, "persisted": False}
    artifacts.append(run_id=run_id, kind=LAB_CONNECTION_SNAPSHOT_KIND, payload=snapshot)
    return connection


def _legacy_connection(service: LabConnectionService, settings: Any) -> ResolvedLabConnection:
    return ResolvedLabConnection(
        provider="bailian",
        mock_enabled=False,
        persisted=False,
        endpoint_url=settings.lab_endpoint_url or "",
        timeout_seconds=settings.lab_timeout_seconds,
        authorization="",
        lab_credentials=service._legacy_tokens(),
    )


def _snapshot_connection(
    database: Session,
    service: LabConnectionService,
    connection: ResolvedLabConnection,
    secrets: SecretStore,
) -> dict[str, Any]:
    profile = service._profiles()[connection.provider]
    labs: dict[str, dict[str, str]] = {}
    if connection.provider == "bootcamp":
        labs = {
            lab_id: {"api_access_id": api_id, "recall_api_access_id": connection.recall_ids.get(lab_id, ""),
                     "name": connection.pair_names.get(lab_id, lab_id)}
            for lab_id, api_id in connection.lab_credentials.items()
        }
    else:
        refs = {
            source.lab_id: source.token_secret_ref
            for source in database.scalars(select(SourceLabModel)).all()
        }
        for lab_id, lab in profile.get("labs", {}).items():
            if lab.get("token_secret_ref"):
                refs[lab_id] = lab["token_secret_ref"]
        for lab_id, token in connection.lab_credentials.items():
            # Environment-only tokens have no existing reference. Encrypt them
            # once so a future environment/configuration change cannot alter
            # the credentials of an explicitly configured in-flight run.
            ref = refs.get(lab_id)
            if ref:
                try:
                    if secrets.get(ref) != token:
                        ref = None
                except Exception:
                    # Resolution may have skipped an unavailable legacy source
                    # credential and selected an environment token instead.
                    ref = None
            if not ref:
                ref = secrets.put(token)
            labs[lab_id] = {"token_secret_ref": ref}

    return {
        "version": 1,
        "persisted": True,
        "provider": connection.provider,
        "mock_enabled": connection.mock_enabled,
        "endpoint_url": connection.endpoint_url,
        "timeout_seconds": connection.timeout_seconds,
        "user_id": connection.user_id,
        "space_id": connection.space_id,
        "authorization_secret_ref": profile.get("authorization_secret_ref"),
        "labs": labs,
    }


def _restore_snapshot(
    snapshot: dict[str, Any],
    secrets: SecretStore,
    *,
    environment: str,
) -> ResolvedLabConnection:
    if snapshot.get("version") != 1 or snapshot.get("provider") not in {"bailian", "bootcamp"}:
        raise ValidationFailed("运行的实验室连接快照无效，请重新发起查询。")
    if snapshot.get("mock_enabled") and environment not in {"development", "test"}:
        raise ValidationFailed("演示数据仅允许在开发或测试环境开启")
    provider = snapshot["provider"]

    def read_secret(ref: str | None) -> str:
        if not ref:
            return ""
        try:
            return secrets.get(ref)
        except Exception:
            raise ValidationFailed("运行使用的实验室密钥已不可用，请重新发起查询。") from None

    credentials = {
        lab_id: (
            read_secret(lab.get("token_secret_ref"))
            if provider == "bailian"
            else lab["api_access_id"]
        )
        for lab_id, lab in snapshot["labs"].items()
    }
    return ResolvedLabConnection(
        provider=provider,
        recall_ids={k:v["recall_api_access_id"] for k,v in snapshot["labs"].items() if v.get("recall_api_access_id")},
        pair_names={k:v["name"] for k,v in snapshot["labs"].items() if v.get("recall_api_access_id") and v.get("name")},
        mock_enabled=snapshot["mock_enabled"],
        persisted=True,
        endpoint_url=snapshot["endpoint_url"],
        timeout_seconds=snapshot["timeout_seconds"],
        authorization=read_secret(snapshot.get("authorization_secret_ref")),
        lab_credentials=credentials,
        user_id=snapshot["user_id"],
        space_id=snapshot["space_id"],
    )
