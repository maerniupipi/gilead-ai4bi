from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, utc_now


class RunArtifactModel(Base):
    __tablename__ = "run_artifacts"
    __table_args__ = (
        UniqueConstraint("run_id", "atom_id", "kind", "revision", name="uq_run_artifact_revision"),
        Index("ix_run_artifacts_trace", "run_id", "kind", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    atom_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    kind: Mapped[str] = mapped_column(String(64), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )


class DatasetEvidenceModel(Base):
    __tablename__ = "dataset_evidence"
    __table_args__ = (Index("ix_dataset_evidence_run_atom", "run_id", "atom_id"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    atom_id: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    approved_sql_id: Mapped[str] = mapped_column(String(64), nullable=False)
    sql_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    data_source_revision_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("data_source_revisions.id", ondelete="RESTRICT"), nullable=False
    )
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    columns_payload: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    rows_payload: Mapped[list[list[Any]]] = mapped_column(JSON, nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    truncated: Mapped[bool] = mapped_column(nullable=False)
    result_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    executed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class FactModel(Base):
    __tablename__ = "facts"
    __table_args__ = (Index("ix_facts_run_atom", "run_id", "atom_id", "kind"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    run_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    atom_id: Mapped[str] = mapped_column(String(64), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    metric: Mapped[str] = mapped_column(String(255), nullable=False)
    value_payload: Mapped[Any] = mapped_column(JSON, nullable=True)
    unit: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    period: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    dimensions: Mapped[list[list[str]]] = mapped_column(JSON, nullable=False)
    lineage: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, nullable=False
    )
