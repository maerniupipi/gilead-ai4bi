from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Union

FactScalar = Union[str, int, float, Decimal, bool, None]


@dataclass(frozen=True)
class RawFact:
    id: str
    run_id: str
    atom_id: str
    metric: str
    value: FactScalar
    unit: str | None
    period: str | None
    dimensions: tuple[tuple[str, str], ...]
    evidence_id: str
    execution_id: str
    approved_sql_id: str
    data_source_revision_id: str
    created_at: datetime
    semantic_scope: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class DerivedFact:
    id: str
    run_id: str
    atom_id: str
    metric: str
    value: FactScalar
    unit: str | None
    period: str | None
    dimensions: tuple[tuple[str, str], ...]
    input_fact_ids: tuple[str, ...]
    calc_plan_id: str
    calc_version: str
    created_at: datetime
    semantic_scope: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FactBundle:
    run_id: str
    raw: tuple[RawFact, ...] = ()
    derived: tuple[DerivedFact, ...] = ()

    @property
    def ids(self) -> tuple[str, ...]:
        return (
            *(fact.id for fact in self.raw),
            *(fact.id for fact in self.derived),
        )


@dataclass(frozen=True)
class FactViewItem:
    id: str
    metric: str
    value: FactScalar
    unit: str | None
    period: str | None
    dimensions: tuple[tuple[str, str], ...]
    citation: str
    semantic_scope: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class FactView:
    run_id: str
    items: tuple[FactViewItem, ...]


@dataclass(frozen=True)
class GapView:
    atom_id: str
    code: str
    message: str
