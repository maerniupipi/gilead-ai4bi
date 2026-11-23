from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import datetime, timezone
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ...modules.context.contracts import (
    MatchMethod,
    PublicationStatus,
    RecallHit,
    RecallLevel,
    RecallRequest,
    RecallSourceType,
)
from ...modules.knowledge import knowledge_is_valid_at
from ..persistence.models.chat import SessionDomainPatchModel
from ..persistence.models.data_sources import (
    DataSourceRevisionModel,
    DomainBindingModel,
    SchemaSnapshotModel,
)
from ..persistence.models.knowledge import (
    KnowledgeEntryModel,
    PersonalMemoryModel,
    PersonalMemoryRevisionModel,
)
from ..persistence.repositories.knowledge import current_published_rows
from .knowledge_seed import is_pinned


class _RuntimeHitArgs(TypedDict):
    request: RecallRequest
    version: str
    publication_status: PublicationStatus
    is_summary: bool
    acl_tags: tuple[str, ...]
    score_override: float
    method_override: MatchMethod


class SqlAlchemyKnowledgeRecallSource:
    """Deterministic first-stage search; ContextBroker remains the ACL authority."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def search(self, request: RecallRequest, *, candidate_limit: int) -> Sequence[RecallHit]:
        candidates = [
            *self._personal(request),
            *self._published(request),
            *self._session_patches(request),
            *self._runtime_domain_cards(request),
        ]
        ranked = sorted(
            candidates, key=lambda item: (-item.score, item.content_id, item.section_id)
        )
        return tuple(ranked[:candidate_limit])

    def _personal(self, request: RecallRequest) -> list[RecallHit]:
        rows = self._session.scalars(
            select(PersonalMemoryModel).where(
                PersonalMemoryModel.owner_id == request.actor_id,
                PersonalMemoryModel.state == "active",
            )
        ).all()
        return [
            self._hit(
                request=request,
                source_type=RecallSourceType.PERSONAL_MEMORY,
                content_id=row.id,
                section_id=row.category,
                version=str(self._personal_version(row.id)),
                content=(
                    self._summary(row.content)
                    if request.level is RecallLevel.L0_RESIDENT
                    else row.content
                ),
                owner_id=row.owner_id,
                publication_status=PublicationStatus.PRIVATE,
                is_summary=True,
            )
            for row in rows
        ]

    def _published(self, request: RecallRequest) -> list[RecallHit]:
        statement = select(KnowledgeEntryModel).where(KnowledgeEntryModel.state == "published")
        recalled_at = datetime.now(timezone.utc)
        effective_rows = [
            row
            for row in self._session.scalars(statement).all()
            if knowledge_is_valid_at(
                row.valid_from,
                row.valid_until,
                instant=recalled_at,
            )
        ]
        rows = current_published_rows(effective_rows)
        output: list[RecallHit] = []
        for row in rows:
            if (
                row.scope == "domain"
                and request.level in {RecallLevel.L2_ATOM_DETAIL, RecallLevel.L3_TARGETED_RECOVERY}
                and request.domain_ids
                and row.domain_id not in request.domain_ids
            ):
                continue
            source_type = (
                RecallSourceType.DOMAIN_KNOWLEDGE
                if row.scope == "domain"
                else RecallSourceType.BUSINESS_KNOWLEDGE
            )
            # Resident only. Planning and answering share L1 and have already
            # had the domain decided for them; handing them the routing rulebook
            # would spend their whole budget on a question they are not asked.
            pinned = request.level is RecallLevel.L0_RESIDENT and is_pinned(row.title)
            # The resident level summarises to keep a catalogue cheap. A routing
            # rule truncated mid-table is worse than absent — it reads as the
            # whole rule — so the rulebook is carried whole or not at all.
            is_l0 = request.level is RecallLevel.L0_RESIDENT and not pinned
            content = self._summary(row.content) if is_l0 else row.content
            hit = self._hit(
                request=request,
                source_type=source_type,
                content_id=row.id,
                section_id=row.title,
                version=str(row.version),
                content=content,
                publication_status=PublicationStatus.PUBLISHED,
                is_summary=is_l0,
                resident_verbatim=pinned,
                score_override=1.0 if pinned else None,
                reason_override="常驻路由规则" if pinned else None,
                acl_tags=(
                    (f"domain:{row.domain_id}",)
                    + (
                        ("reviewed_route",)
                        if row.source_candidate_id and row.title.startswith("澄清形成的")
                        else ()
                    )
                    if row.domain_id
                    else ()
                ),
            )
            if (
                row.scope == "domain"
                and request.level is RecallLevel.L2_ATOM_DETAIL
                and row.domain_id in request.domain_ids
                and hit.score < 0.55
            ):
                hit = RecallHit(
                    source_type=hit.source_type,
                    content_id=hit.content_id,
                    section_id=hit.section_id,
                    version=hit.version,
                    content=hit.content,
                    score=0.55,
                    match_method=MatchMethod.STRUCTURED,
                    matched_reason="已确认域的执行知识",
                    token_count=hit.token_count,
                    owner_id=hit.owner_id,
                    session_id=hit.session_id,
                    topic_id=hit.topic_id,
                    content_hash=hit.content_hash,
                    publication_status=hit.publication_status,
                    rejected_reason=hit.rejected_reason,
                    is_summary=hit.is_summary,
                    resident_verbatim=hit.resident_verbatim,
                    from_session_patch=hit.from_session_patch,
                    acl_tags=hit.acl_tags,
                )
            output.append(hit)
        return output

    def _personal_version(self, memory_id: str) -> int:
        version = self._session.scalar(
            select(func.max(PersonalMemoryRevisionModel.version)).where(
                PersonalMemoryRevisionModel.memory_id == memory_id
            )
        )
        return int(version or 1)

    def _session_patches(self, request: RecallRequest) -> list[RecallHit]:
        if not request.topic_id:
            return []
        rows = self._session.scalars(
            select(SessionDomainPatchModel)
            .where(
                SessionDomainPatchModel.session_id == request.session_id,
                SessionDomainPatchModel.topic_id == request.topic_id,
                SessionDomainPatchModel.active.is_(True),
            )
            .order_by(
                SessionDomainPatchModel.created_at.desc(),
                SessionDomainPatchModel.id.desc(),
            )
        ).all()
        output: list[RecallHit] = []
        for row in rows:
            selected = "、".join(row.selected_domains)
            content = f"本会话已澄清域：{selected}；补丁={row.payload}"
            output.append(
                self._hit(
                    request=request,
                    source_type=RecallSourceType.SESSION_STATE,
                    content_id=row.id,
                    section_id="domain_patch",
                    version="1",
                    content=content,
                    session_id=row.session_id,
                    topic_id=row.topic_id,
                    publication_status=PublicationStatus.PRIVATE,
                    is_summary=True,
                    from_session_patch=True,
                    acl_tags=tuple(f"domain:{domain_id}" for domain_id in row.selected_domains),
                    score_override=0.99,
                    method_override=MatchMethod.SESSION_PATCH,
                    reason_override="当前会话已确认的域补丁",
                )
            )
        return output

    def _runtime_domain_cards(self, request: RecallRequest) -> list[RecallHit]:
        if request.level not in {
            RecallLevel.L2_ATOM_DETAIL,
            RecallLevel.L3_TARGETED_RECOVERY,
        }:
            return []
        output: list[RecallHit] = []
        for domain_id in request.domain_ids:
            binding = self._session.scalar(
                select(DomainBindingModel)
                .where(
                    DomainBindingModel.domain_id == domain_id,
                    DomainBindingModel.active.is_(True),
                )
                .order_by(DomainBindingModel.created_at.desc())
            )
            if binding is None:
                continue
            revision = self._session.get(
                DataSourceRevisionModel,
                binding.data_source_revision_id,
            )
            if revision is None:
                continue
            method = (
                MatchMethod.TARGETED_ERROR
                if request.level is RecallLevel.L3_TARGETED_RECOVERY
                else MatchMethod.STRUCTURED
            )
            common: _RuntimeHitArgs = {
                "request": request,
                "version": f"revision:{revision.revision}",
                "publication_status": PublicationStatus.PUBLISHED,
                "is_summary": False,
                "acl_tags": (f"domain:{domain_id}", f"revision:{revision.id}"),
                "score_override": 0.98,
                "method_override": method,
            }
            output.append(
                self._hit(
                    source_type=RecallSourceType.LAB_CONSTRAINT,
                    content_id=f"lab:{binding.lab_id}",
                    section_id="quick_lab_contract",
                    content=(
                        f"域 {domain_id} 使用实验室 {binding.lab_id}；"
                        "平台只接收 rewritten query 与候选 SQL，其他响应字段不可信。"
                    ),
                    reason_override="已确认域绑定的实验室契约",
                    **common,
                )
            )
            output.append(
                self._hit(
                    source_type=RecallSourceType.SQL_POLICY,
                    content_id=f"sql-policy:{revision.id}",
                    section_id="domain_sql_policy",
                    content=(
                        f"selected_database={revision.selected_database}; "
                        f"schema={revision.schema_name or '-'}; "
                        f"allowed_objects={','.join(revision.allowed_objects)}; "
                        f"allowed_schemas={','.join(revision.allowed_schemas)}; "
                        f"timeout_seconds={revision.query_timeout_seconds}; "
                        f"max_rows={revision.max_rows}."
                    ),
                    reason_override="固化数据源版本的 SQL 策略",
                    **common,
                )
            )
            if revision.schema_snapshot_id:
                snapshot = self._session.get(
                    SchemaSnapshotModel,
                    revision.schema_snapshot_id,
                )
                if snapshot is not None:
                    column_cards = "; ".join(
                        f"{name}({','.join(columns[:80])})"
                        for name, columns in sorted(snapshot.columns.items())
                    )
                    output.append(
                        self._hit(
                            source_type=RecallSourceType.SCHEMA_CARD,
                            content_id=f"schema:{snapshot.id}",
                            section_id="frozen_schema_card",
                            content=(
                                f"schema_fingerprint={snapshot.fingerprint}; "
                                f"objects={','.join(snapshot.objects)}; columns={column_cards}"
                            ),
                            reason_override="固化数据源版本的 Schema 快照",
                            **common,
                        )
                    )
        return output

    def _hit(
        self,
        *,
        request: RecallRequest,
        source_type: RecallSourceType,
        content_id: str,
        section_id: str,
        version: str,
        content: str,
        publication_status: PublicationStatus,
        owner_id: str | None = None,
        session_id: str | None = None,
        topic_id: str | None = None,
        is_summary: bool = False,
        resident_verbatim: bool = False,
        from_session_patch: bool = False,
        acl_tags: tuple[str, ...] = (),
        score_override: float | None = None,
        method_override: MatchMethod | None = None,
        reason_override: str | None = None,
    ) -> RecallHit:
        score, reason, method = self._score(request.query, f"{section_id}\n{content}")
        if request.level is RecallLevel.L0_RESIDENT:
            score = max(score, 0.72)
            reason = "L0 常驻目录/摘要"
            method = MatchMethod.RESIDENT
        if score_override is not None:
            score = score_override
        if reason_override is not None:
            reason = reason_override
        if method_override is not None:
            method = method_override
        return RecallHit(
            source_type=source_type,
            content_id=content_id,
            section_id=section_id,
            version=version,
            content=content,
            score=score,
            match_method=method,
            matched_reason=reason,
            token_count=max(1, len(content) // 2),
            owner_id=owner_id,
            session_id=session_id,
            topic_id=topic_id,
            publication_status=publication_status,
            is_summary=is_summary,
            resident_verbatim=resident_verbatim,
            from_session_patch=from_session_patch,
            acl_tags=acl_tags,
        )

    @classmethod
    def _score(cls, query: str, content: str) -> tuple[float, str, MatchMethod]:
        query_tokens = cls._tokens(query)
        content_tokens = cls._tokens(content)
        if not query_tokens:
            return 0.2, "无查询词，使用目录顺序", MatchMethod.STRUCTURED
        overlap = query_tokens.intersection(content_tokens)
        if overlap:
            ratio = len(overlap) / max(1, len(query_tokens))
            return (
                min(1.0, 0.5 + ratio * 0.5),
                f"命中：{'、'.join(sorted(overlap)[:8])}",
                MatchMethod.FULL_TEXT,
            )
        return 0.1, "未命中关键词，作为低分候选", MatchMethod.STRUCTURED

    @staticmethod
    def _tokens(text: str) -> set[str]:
        lowered = text.casefold()
        ascii_words = set(re.findall(r"[a-z0-9_%]+", lowered))
        chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
        bigrams = {chinese[index : index + 2] for index in range(max(0, len(chinese) - 1))}
        return {token for token in (*ascii_words, *bigrams) if token}

    @staticmethod
    def _summary(content: str) -> str:
        compact = "\n".join(line for line in content.splitlines() if line.strip())
        return compact[:800]
