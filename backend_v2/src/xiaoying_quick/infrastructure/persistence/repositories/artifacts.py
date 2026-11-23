from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, is_dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, cast

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ....modules.execution.contracts import DataColumn, DatasetEvidence, EvidenceState
from ....modules.facts.contracts import DerivedFact, FactBundle, FactScalar, RawFact
from ....shared.ids import new_id
from ..models.artifacts import DatasetEvidenceModel, FactModel, RunArtifactModel
from ..models.runs import RunModel


class SqlAlchemyArtifactRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def append(
        self, *, run_id: str, kind: str, payload: dict[str, Any], atom_id: str | None = None
    ) -> str:
        revision = self._session.scalar(
            select(func.max(RunArtifactModel.revision)).where(
                RunArtifactModel.run_id == run_id,
                RunArtifactModel.atom_id.is_(atom_id)
                if atom_id is None
                else RunArtifactModel.atom_id == atom_id,
                RunArtifactModel.kind == kind,
            )
        )
        artifact_id = new_id("artifact")
        self._session.add(
            RunArtifactModel(
                id=artifact_id,
                run_id=run_id,
                atom_id=atom_id,
                kind=kind,
                revision=int(revision or 0) + 1,
                payload=self._json_safe(payload),
            )
        )
        self._session.flush()
        return artifact_id

    def get(self, artifact_id: str) -> dict[str, Any] | None:
        row = self._session.get(RunArtifactModel, artifact_id)
        if row is None:
            return None
        return {
            "id": row.id,
            "run_id": row.run_id,
            "kind": row.kind,
            "atom_id": row.atom_id,
            "revision": row.revision,
            "payload": row.payload,
            "created_at": row.created_at.isoformat(),
        }

    def list_for_run(self, run_id: str) -> list[dict[str, Any]]:
        ids = self._session.scalars(
            select(RunArtifactModel.id)
            .where(RunArtifactModel.run_id == run_id)
            .order_by(RunArtifactModel.created_at, RunArtifactModel.revision, RunArtifactModel.id)
        ).all()
        rows = self._load_in_order(ids)
        return [
            {
                "id": row.id,
                "kind": row.kind,
                "atom_id": row.atom_id,
                "revision": row.revision,
                "payload": row.payload,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ]

    def tool_records(self, run_id: str, name: str) -> list[dict[str, Any]]:
        """Read SQL provenance without loading query result grids or conversation history."""
        model = RunArtifactModel
        payload = model.payload["payload"]
        rows = self._session.execute(
            select(model.payload["ok"].as_boolean(), payload["sql"].as_string(),
                   payload["sql_ref"].as_string(), payload["source_sql_refs"])
            .where(model.run_id == run_id, model.kind == "tool_result",
                   model.payload["name"].as_string() == name)
            .order_by(model.created_at, model.revision, model.id)
        )
        return [{"ok": ok, "payload": {"sql": sql, "sql_ref": ref, "source_sql_refs": refs}}
                for ok, sql, ref, refs in rows]

    def latest(
        self, *, run_id: str, kind: str, atom_id: str | None = None
    ) -> dict[str, Any] | None:
        statement = select(RunArtifactModel.id).where(
            RunArtifactModel.run_id == run_id,
            RunArtifactModel.kind == kind,
        )
        statement = (
            statement.where(RunArtifactModel.atom_id.is_(None))
            if atom_id is None
            else statement.where(RunArtifactModel.atom_id == atom_id)
        )
        artifact_id = self._session.scalar(
            statement.order_by(
                RunArtifactModel.revision.desc(), RunArtifactModel.created_at.desc()
            ).limit(1)
        )
        row = self._session.get(RunArtifactModel, artifact_id) if artifact_id else None
        return dict(row.payload) if row else None

    def latest_for_session(
        self,
        *,
        session_id: str,
        kind: str,
        excluding_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Return the newest durable artifact for an earlier run in a chat session."""

        statement = (
            select(RunArtifactModel.id)
            .join(RunModel, RunModel.id == RunArtifactModel.run_id)
            .where(
                RunModel.session_id == session_id,
                RunArtifactModel.kind == kind,
                RunArtifactModel.atom_id.is_(None),
            )
        )
        if excluding_run_id is not None:
            statement = statement.where(RunArtifactModel.run_id != excluding_run_id)
        artifact_id = self._session.scalar(
            statement.order_by(
                RunArtifactModel.created_at.desc(),
                RunArtifactModel.revision.desc(),
            ).limit(1)
        )
        row = self._session.get(RunArtifactModel, artifact_id) if artifact_id else None
        return dict(row.payload) if row else None

    def list_for_session(
        self,
        *,
        session_id: str,
        kind: str,
        excluding_run_id: str | None = None,
        limit: int | None = 16,
        workbook_ids: Sequence[str] | None = None,
    ) -> tuple[dict[str, Any], ...]:
        """Newest query-frame (or other artifact) per earlier run, oldest first."""

        statement = (
            select(RunArtifactModel.id, RunArtifactModel.run_id, RunModel.insight_meta)
            .join(RunModel, RunModel.id == RunArtifactModel.run_id)
            .where(
                RunModel.session_id == session_id,
                RunArtifactModel.kind == kind,
                RunArtifactModel.atom_id.is_(None),
            )
        )
        if excluding_run_id is not None:
            statement = statement.where(RunArtifactModel.run_id != excluding_run_id)
        refs = self._session.execute(
            statement.order_by(
                RunArtifactModel.created_at.desc(),
                RunArtifactModel.revision.desc(),
            )
        ).all()
        picked: list[str] = []
        seen_runs: set[str] = set()
        for artifact_id, run_id, meta in refs:
            if (
                workbook_ids is not None
                and set((meta or {}).get("workbook_ids") or []) != set(workbook_ids)
            ):
                continue
            if run_id in seen_runs:
                continue
            seen_runs.add(run_id)
            picked.append(artifact_id)
            if limit is not None and len(picked) >= max(1, limit):
                break
        rows = reversed(self._load_in_order(picked))
        if kind == "agent_transcript":
            return tuple({**row.payload, "context_run_id": row.run_id} for row in rows)
        return tuple(dict(row.payload) for row in rows)

    def report_for_session(
        self,
        *,
        session_id: str,
        report_id: str,
        revision: int | None = None,
        excluding_run_id: str | None = None,
    ) -> dict[str, Any] | None:
        """Resolve the report the user actually edited, within the owned session."""
        statement = (
            select(RunArtifactModel.id)
            .join(RunModel, RunModel.id == RunArtifactModel.run_id)
            .where(
                RunModel.session_id == session_id,
                RunArtifactModel.kind == "bi_report",
                RunArtifactModel.payload["id"].as_string() == report_id,
            )
        )
        if revision is not None:
            statement = statement.where(
                RunArtifactModel.payload["revision"].as_integer() == revision
            )
        if excluding_run_id:
            statement = statement.where(RunArtifactModel.run_id != excluding_run_id)
        artifact_id = self._session.scalar(
            statement.order_by(
                RunArtifactModel.created_at.desc(), RunArtifactModel.revision.desc()
            ).limit(1)
        )
        row = self._session.get(RunArtifactModel, artifact_id) if artifact_id else None
        return dict(row.payload) if row else None

    def _load_in_order(self, ids) -> list[RunArtifactModel]:
        """Sort small IDs, then fetch JSON without a MySQL filesort of large payloads."""
        if not ids:
            return []
        rows = self._session.scalars(
            select(RunArtifactModel).where(RunArtifactModel.id.in_(ids))
        ).all()
        by_id = {row.id: row for row in rows}
        return [by_id[artifact_id] for artifact_id in ids if artifact_id in by_id]

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if is_dataclass(value) and not isinstance(value, type):
            return cls._json_safe(asdict(cast(Any, value)))
        if isinstance(value, dict):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (tuple, list)):
            return [cls._json_safe(item) for item in value]
        if isinstance(value, Decimal):
            return {"__decimal__": str(value)}
        if isinstance(value, datetime):
            return value.isoformat()
        if hasattr(value, "value") and isinstance(value.value, (str, int, float, bool)):
            return value.value
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        return str(value)


class SqlAlchemyEvidenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save(self, evidence: DatasetEvidence) -> DatasetEvidence:
        self._session.add(
            DatasetEvidenceModel(
                id=evidence.id,
                run_id=evidence.run_id,
                atom_id=evidence.atom_id,
                execution_id=evidence.execution_id,
                approved_sql_id=evidence.approved_sql_id,
                sql_fingerprint=evidence.sql_fingerprint,
                data_source_revision_id=evidence.data_source_revision_id,
                state=evidence.state.value,
                columns_payload=[
                    {"name": value.name, "logical_type": value.logical_type}
                    for value in evidence.columns
                ],
                rows_payload=[list(row) for row in evidence.rows],
                row_count=evidence.row_count,
                truncated=evidence.truncated,
                result_hash=evidence.result_hash,
                duration_ms=evidence.duration_ms,
                executed_at=evidence.executed_at,
            )
        )
        self._session.flush()
        return evidence

    def get(self, evidence_id: str) -> DatasetEvidence | None:
        row = self._session.get(DatasetEvidenceModel, evidence_id)
        return self._evidence(row) if row else None

    def for_run(self, run_id: str) -> tuple[DatasetEvidence, ...]:
        rows = self._session.scalars(
            select(DatasetEvidenceModel)
            .where(DatasetEvidenceModel.run_id == run_id)
            .order_by(DatasetEvidenceModel.executed_at, DatasetEvidenceModel.id)
        ).all()
        return tuple(self._evidence(row) for row in rows)

    @staticmethod
    def _evidence(row: DatasetEvidenceModel) -> DatasetEvidence:
        return DatasetEvidence(
            id=row.id,
            run_id=row.run_id,
            atom_id=row.atom_id,
            execution_id=row.execution_id,
            approved_sql_id=row.approved_sql_id,
            sql_fingerprint=row.sql_fingerprint,
            data_source_revision_id=row.data_source_revision_id,
            state=EvidenceState(row.state),
            columns=tuple(DataColumn(**column) for column in row.columns_payload),
            rows=tuple(tuple(value for value in values) for values in row.rows_payload),
            row_count=row.row_count,
            truncated=row.truncated,
            result_hash=row.result_hash,
            duration_ms=row.duration_ms,
            executed_at=row.executed_at,
        )


class SqlAlchemyFactRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def save_raw(self, facts: tuple[RawFact, ...]) -> tuple[RawFact, ...]:
        for fact in facts:
            self._session.add(self._raw_model(fact))
        self._session.flush()
        return facts

    def save_derived(self, facts: tuple[DerivedFact, ...]) -> tuple[DerivedFact, ...]:
        for fact in facts:
            self._session.add(self._derived_model(fact))
        self._session.flush()
        return facts

    def for_run(self, run_id: str) -> FactBundle:
        rows = self._session.scalars(
            select(FactModel).where(FactModel.run_id == run_id).order_by(FactModel.created_at)
        ).all()
        raw = tuple(self._raw(row) for row in rows if row.kind == "raw")
        derived = tuple(self._derived(row) for row in rows if row.kind == "derived")
        return FactBundle(run_id=run_id, raw=raw, derived=derived)

    @classmethod
    def _raw_model(cls, fact: RawFact) -> FactModel:
        return FactModel(
            id=fact.id,
            run_id=fact.run_id,
            atom_id=fact.atom_id,
            kind="raw",
            metric=fact.metric,
            value_payload=cls._encode_value(fact.value),
            unit=fact.unit,
            period=fact.period,
            dimensions=[list(item) for item in fact.dimensions],
            lineage={
                "evidence_id": fact.evidence_id,
                "execution_id": fact.execution_id,
                "approved_sql_id": fact.approved_sql_id,
                "data_source_revision_id": fact.data_source_revision_id,
                "semantic_scope": [list(item) for item in fact.semantic_scope],
            },
            created_at=fact.created_at,
        )

    @classmethod
    def _derived_model(cls, fact: DerivedFact) -> FactModel:
        return FactModel(
            id=fact.id,
            run_id=fact.run_id,
            atom_id=fact.atom_id,
            kind="derived",
            metric=fact.metric,
            value_payload=cls._encode_value(fact.value),
            unit=fact.unit,
            period=fact.period,
            dimensions=[list(item) for item in fact.dimensions],
            lineage={
                "input_fact_ids": list(fact.input_fact_ids),
                "calc_plan_id": fact.calc_plan_id,
                "calc_version": fact.calc_version,
                "semantic_scope": [list(item) for item in fact.semantic_scope],
            },
            created_at=fact.created_at,
        )

    @classmethod
    def _raw(cls, row: FactModel) -> RawFact:
        return RawFact(
            id=row.id,
            run_id=row.run_id,
            atom_id=row.atom_id,
            metric=row.metric,
            value=cls._decode_value(row.value_payload),
            unit=row.unit,
            period=row.period,
            dimensions=tuple((str(k), str(v)) for k, v in row.dimensions),
            evidence_id=str(row.lineage["evidence_id"]),
            execution_id=str(row.lineage["execution_id"]),
            approved_sql_id=str(row.lineage["approved_sql_id"]),
            data_source_revision_id=str(row.lineage["data_source_revision_id"]),
            created_at=row.created_at,
            semantic_scope=tuple(
                (str(k), str(v)) for k, v in row.lineage.get("semantic_scope", ())
            ),
        )

    @classmethod
    def _derived(cls, row: FactModel) -> DerivedFact:
        return DerivedFact(
            id=row.id,
            run_id=row.run_id,
            atom_id=row.atom_id,
            metric=row.metric,
            value=cls._decode_value(row.value_payload),
            unit=row.unit,
            period=row.period,
            dimensions=tuple((str(k), str(v)) for k, v in row.dimensions),
            input_fact_ids=tuple(str(value) for value in row.lineage["input_fact_ids"]),
            calc_plan_id=str(row.lineage["calc_plan_id"]),
            calc_version=str(row.lineage["calc_version"]),
            created_at=row.created_at,
            semantic_scope=tuple(
                (str(k), str(v)) for k, v in row.lineage.get("semantic_scope", ())
            ),
        )

    @staticmethod
    def _encode_value(value: FactScalar) -> dict[str, FactScalar]:
        if isinstance(value, Decimal):
            return {"type": "decimal", "value": str(value)}
        return {"type": "scalar", "value": value}

    @staticmethod
    def _decode_value(payload: dict[str, Any]) -> FactScalar:
        if payload.get("type") == "decimal":
            return Decimal(payload["value"])
        return cast(FactScalar, payload.get("value"))
