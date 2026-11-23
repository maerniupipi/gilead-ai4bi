from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, TimestampMixin, utc_now


class DataSourceModel(TimestampMixin, Base):
    __tablename__ = "data_sources"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False, unique=True)
    connection_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    selected_database: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dialect: Mapped[str] = mapped_column(String(32), nullable=False)
    ssl_mode: Mapped[str] = mapped_column(String(32), nullable=False, default="disable")
    state: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    current_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    secret_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    allowed_objects: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_schemas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    query_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    max_rows: Mapped[int] = mapped_column(Integer, nullable=False, default=2000)
    allow_private_network: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class SchemaSnapshotModel(Base):
    __tablename__ = "data_source_schema_snapshots"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    objects: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    columns: Mapped[dict[str, list[str]]] = mapped_column(JSON, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DataSourceRevisionModel(Base):
    __tablename__ = "data_source_revisions"
    __table_args__ = (
        UniqueConstraint("data_source_id", "revision", name="uq_data_source_revision"),
        Index("ix_data_source_revisions_created", "data_source_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    connection_url: Mapped[str] = mapped_column(Text, nullable=False)
    username: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    selected_database: Mapped[str] = mapped_column(String(255), nullable=False)
    schema_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    dialect: Mapped[str] = mapped_column(String(32), nullable=False)
    ssl_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    secret_ref: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    allowed_objects: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    allowed_schemas: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    query_timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_rows: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_private_network: Mapped[bool] = mapped_column(Boolean, nullable=False)
    schema_snapshot_id: Mapped[Optional[str]] = mapped_column(
        String(64),
        ForeignKey("data_source_schema_snapshots.id", ondelete="RESTRICT"),
        nullable=True,
    )
    created_by: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class SourceLabModel(Base):
    __tablename__ = "source_labs"
    __table_args__ = (UniqueConstraint("lab_id", name="uq_source_labs_lab_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    data_source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_sources.id", ondelete="CASCADE"), nullable=False, index=True
    )
    lab_id: Mapped[str] = mapped_column(String(128), nullable=False)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    token_secret_ref: Mapped[str] = mapped_column(String(128), nullable=False)
    created_by: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class DomainBindingModel(Base):
    __tablename__ = "domain_bindings"
    __table_args__ = (Index("ix_domain_bindings_active", "domain_id", "active"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    domain_id: Mapped[str] = mapped_column(String(64), nullable=False)
    lab_id: Mapped[str] = mapped_column(String(64), nullable=False)
    data_source_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_sources.id", ondelete="RESTRICT"), nullable=False
    )
    data_source_revision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_source_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    allowed_objects: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_schemas: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    allowed_join_keys: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_by: Mapped[str] = mapped_column(
        String(64), ForeignKey("identity_users.id", ondelete="RESTRICT"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class AuditEventModel(Base):
    __tablename__ = "audit_events"
    __table_args__ = (Index("ix_audit_resource_created", "resource_id", "created_at"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    actor_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(128), nullable=False)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
