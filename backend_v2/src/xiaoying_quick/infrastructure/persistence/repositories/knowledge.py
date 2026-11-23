from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session
from ....modules.knowledge.library import is_markdown

from ....modules.knowledge.contracts import (
    CandidateRequest,
    KnowledgeCandidate,
    KnowledgeEntry,
    KnowledgeScope,
    KnowledgeState,
    MemoryUpdateRequest,
    MemoryWriteRequest,
    PersonalMemoryEntry,
    PersonalMemoryRevision,
    knowledge_logical_key,
)
from ....shared.ids import new_id
from ..models.knowledge import (
    KnowledgeCandidateModel,
    KnowledgeEntryModel,
    PersonalMemoryModel,
    PersonalMemoryRevisionModel,
)


def current_published_rows(
    rows: Iterable[KnowledgeEntryModel],
) -> list[KnowledgeEntryModel]:
    """Collapse legacy duplicate published rows to the current logical version."""

    current: dict[str, KnowledgeEntryModel] = {}
    for row in rows:
        if row.state != KnowledgeState.PUBLISHED.value:
            continue
        logical_key = knowledge_logical_key(
            KnowledgeScope(row.scope),
            row.domain_id,
            row.title,
        )
        selected = current.get(logical_key)
        if selected is None or _knowledge_version_order(row) > _knowledge_version_order(selected):
            current[logical_key] = row
    return sorted(
        current.values(),
        key=lambda row: (row.published_at, row.version, row.id),
        reverse=True,
    )


def _knowledge_version_order(row: KnowledgeEntryModel) -> tuple[int, datetime, str]:
    return row.version, row.published_at, row.id


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SqlAlchemyPersonalMemoryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_for_owner(
        self, owner_id: str, *, include_revoked: bool = False
    ) -> list[PersonalMemoryEntry]:
        statement = select(PersonalMemoryModel).where(PersonalMemoryModel.owner_id == owner_id)
        if not include_revoked:
            statement = statement.where(PersonalMemoryModel.state == KnowledgeState.ACTIVE.value)
        rows = self._session.scalars(
            statement.order_by(PersonalMemoryModel.created_at.desc())
        ).all()
        return [self._entry(row) for row in rows]

    def create(
        self, entry_id: str, owner_id: str, request: MemoryWriteRequest
    ) -> PersonalMemoryEntry:
        row = PersonalMemoryModel(
            id=entry_id,
            owner_id=owner_id,
            category=request.category.strip() or "preference",
            content=request.content,
            source_run_id=request.source_run_id,
            state=KnowledgeState.ACTIVE.value,
        )
        self._session.add(row)
        self._session.flush()
        self._append_revision(row, version=1, state=KnowledgeState.ACTIVE)
        self._session.flush()
        return self._entry(row, version=1)

    def update(
        self,
        entry_id: str,
        owner_id: str,
        request: MemoryUpdateRequest,
    ) -> PersonalMemoryEntry:
        row = self._owned_row(entry_id, owner_id, lock=True)
        if row.state != KnowledgeState.ACTIVE.value:
            raise ValueError("only active personal memory can be updated")
        current_version = self._ensure_revision_baseline(row)
        row.category = request.category.strip() or "preference"
        row.content = request.content
        row.source_run_id = request.source_run_id
        row.revoked_at = None
        version = current_version + 1
        self._append_revision(row, version=version, state=KnowledgeState.ACTIVE)
        self._session.flush()
        return self._entry(row, version=version)

    def revoke(self, entry_id: str, owner_id: str) -> PersonalMemoryEntry:
        row = self._owned_row(entry_id, owner_id, lock=True)
        if row.state != KnowledgeState.ACTIVE.value:
            raise ValueError("only active personal memory can be revoked")
        current_version = self._ensure_revision_baseline(row)
        row.state = KnowledgeState.REVOKED.value
        row.revoked_at = datetime.now(timezone.utc)
        version = current_version + 1
        self._append_revision(row, version=version, state=KnowledgeState.REVOKED)
        self._session.flush()
        return self._entry(row, version=version)

    def history(self, entry_id: str, owner_id: str) -> list[PersonalMemoryRevision]:
        row = self._owned_row(entry_id, owner_id)
        revisions = self._session.scalars(
            select(PersonalMemoryRevisionModel)
            .where(PersonalMemoryRevisionModel.memory_id == row.id)
            .order_by(PersonalMemoryRevisionModel.version)
        ).all()
        if revisions:
            return [self._revision(revision) for revision in revisions]
        return self._legacy_history(row)

    def _owned_row(
        self,
        entry_id: str,
        owner_id: str,
        *,
        lock: bool = False,
    ) -> PersonalMemoryModel:
        statement = select(PersonalMemoryModel).where(
            PersonalMemoryModel.id == entry_id,
            PersonalMemoryModel.owner_id == owner_id,
        )
        if lock:
            statement = statement.with_for_update()
        row = self._session.scalar(statement)
        if row is None:
            raise LookupError(entry_id)
        return row

    def _ensure_revision_baseline(self, row: PersonalMemoryModel) -> int:
        current_version = self._session.scalar(
            select(func.max(PersonalMemoryRevisionModel.version)).where(
                PersonalMemoryRevisionModel.memory_id == row.id
            )
        )
        if current_version is not None:
            return int(current_version)
        self._append_revision(
            row,
            version=1,
            state=KnowledgeState.ACTIVE,
            created_at=row.created_at,
        )
        if row.state == KnowledgeState.REVOKED.value:
            self._append_revision(
                row,
                version=2,
                state=KnowledgeState.REVOKED,
                created_at=row.revoked_at or row.created_at,
            )
            return 2
        return 1

    def _append_revision(
        self,
        row: PersonalMemoryModel,
        *,
        version: int,
        state: KnowledgeState,
        created_at: datetime | None = None,
    ) -> None:
        self._session.add(
            PersonalMemoryRevisionModel(
                id=new_id("memrev"),
                memory_id=row.id,
                version=version,
                category=row.category,
                content=row.content,
                source_run_id=row.source_run_id,
                state=state.value,
                created_at=created_at or datetime.now(timezone.utc),
            )
        )

    def _entry(
        self, row: PersonalMemoryModel, *, version: int | None = None
    ) -> PersonalMemoryEntry:
        if version is None:
            version = self._session.scalar(
                select(func.max(PersonalMemoryRevisionModel.version)).where(
                    PersonalMemoryRevisionModel.memory_id == row.id
                )
            )
        return PersonalMemoryEntry(
            id=row.id,
            owner_id=row.owner_id,
            category=row.category,
            content=row.content,
            source_run_id=row.source_run_id,
            state=KnowledgeState(row.state),
            created_at=row.created_at,
            revoked_at=row.revoked_at,
            version=int(version or 1),
        )

    @staticmethod
    def _revision(row: PersonalMemoryRevisionModel) -> PersonalMemoryRevision:
        return PersonalMemoryRevision(
            id=row.id,
            memory_id=row.memory_id,
            version=row.version,
            category=row.category,
            content=row.content,
            source_run_id=row.source_run_id,
            state=KnowledgeState(row.state),
            created_at=row.created_at,
        )

    @staticmethod
    def _legacy_history(row: PersonalMemoryModel) -> list[PersonalMemoryRevision]:
        baseline = PersonalMemoryRevision(
            id=f"legacy:{row.id}:1",
            memory_id=row.id,
            version=1,
            category=row.category,
            content=row.content,
            source_run_id=row.source_run_id,
            state=KnowledgeState.ACTIVE,
            created_at=row.created_at,
        )
        if row.state != KnowledgeState.REVOKED.value:
            return [baseline]
        return [
            baseline,
            PersonalMemoryRevision(
                id=f"legacy:{row.id}:2",
                memory_id=row.id,
                version=2,
                category=row.category,
                content=row.content,
                source_run_id=row.source_run_id,
                state=KnowledgeState.REVOKED,
                created_at=row.revoked_at or row.created_at,
            ),
        ]


class SqlAlchemyKnowledgeRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_candidates(self, state: KnowledgeState | None = None) -> list[KnowledgeCandidate]:
        statement = select(KnowledgeCandidateModel)
        if state is not None:
            statement = statement.where(KnowledgeCandidateModel.state == state.value)
        rows = self._session.scalars(
            statement.order_by(KnowledgeCandidateModel.created_at.desc())
        ).all()
        return [self._candidate(row) for row in rows]

    def get_candidate(self, candidate_id: str) -> KnowledgeCandidate | None:
        row = self._session.get(KnowledgeCandidateModel, candidate_id)
        return self._candidate(row) if row else None

    def create_candidate(
        self,
        candidate_id: str,
        request: CandidateRequest,
        source_user_id: str,
    ) -> KnowledgeCandidate:
        row = KnowledgeCandidateModel(
            id=candidate_id,
            scope=request.scope.value,
            domain_id=request.domain_id,
            title=request.title.strip(),
            content=request.content,
            rationale=request.rationale.strip(),
            evidence_refs=list(request.evidence_refs),
            source_run_id=request.source_run_id,
            source_question=request.source_question,
            clarification_question=request.clarification_question,
            clarification_answer=request.clarification_answer,
            applicability=request.applicability,
            valid_from=request.valid_from,
            valid_until=request.valid_until,
            source_user_id=source_user_id,
            state=KnowledgeState.PENDING_REVIEW.value,
        )
        self._session.add(row)
        self._session.flush()
        return self._candidate(row)

    def mark_reviewed(
        self,
        candidate_id: str,
        state: KnowledgeState,
        reviewer_id: str,
        comment: str | None,
        edited_content: str | None = None,
    ) -> KnowledgeCandidate:
        row = self._session.get(KnowledgeCandidateModel, candidate_id, with_for_update=True, populate_existing=True)
        if row is None:
            raise LookupError(candidate_id)
        if row.state != KnowledgeState.PENDING_REVIEW.value:
            raise ValueError("candidate was already reviewed")
        row.state = state.value
        row.reviewed_by = reviewer_id
        row.reviewed_at = datetime.now(timezone.utc)
        row.review_comment = comment
        if edited_content is not None:
            row.content = edited_content
        self._session.flush()
        return self._candidate(row)

    def publish(self, candidate: KnowledgeCandidate, publisher_id: str) -> KnowledgeEntry:
        if candidate.state is not KnowledgeState.APPROVED_PENDING_PUBLISH:
            raise ValueError("candidate is not approved for publication")
        logical_key = candidate.logical_key
        # The first upload of a name has no existing version to lock.
        if self._session.get_bind().dialect.name == "postgresql":
            lock_id = int.from_bytes(hashlib.sha256(logical_key.encode()).digest()[:8], "big", signed=True)
            self._session.execute(select(func.pg_advisory_xact_lock(lock_id)))
        scope_rows = self._session.scalars(
            select(KnowledgeEntryModel)
            .where(KnowledgeEntryModel.scope == candidate.scope.value)
            .with_for_update()
        ).all()
        matching = [
            row
            for row in scope_rows
            if knowledge_logical_key(KnowledgeScope(row.scope), row.domain_id, row.title)
            == logical_key
        ]
        current_version = max((row.version for row in matching), default=0)
        content_hash = hashlib.sha256(candidate.content.encode("utf-8")).hexdigest()
        if is_markdown(candidate.title):
            for current in matching:
                if (current.state == KnowledgeState.PUBLISHED.value and current.version == current_version
                        and current.content_hash == content_hash and current.applicability == candidate.applicability
                        and current.valid_from == candidate.valid_from and current.valid_until == candidate.valid_until):
                    return self._published(current)
        for previous in matching:
            if previous.state == KnowledgeState.PUBLISHED.value:
                previous.state = KnowledgeState.SUPERSEDED.value
        row = KnowledgeEntryModel(
            id=new_id("knowledge"),
            scope=candidate.scope.value,
            domain_id=candidate.domain_id,
            title=candidate.title,
            content=candidate.content,
            version=current_version + 1,
            content_hash=content_hash,
            source_candidate_id=candidate.id,
            applicability=candidate.applicability,
            valid_from=candidate.valid_from,
            valid_until=candidate.valid_until,
            state=KnowledgeState.PUBLISHED.value,
            published_by=publisher_id,
        )
        self._session.add(row)
        self._session.flush()
        return self._published(row)

    def effective_entries(self, instant: datetime) -> list[KnowledgeEntry]:
        model = KnowledgeEntryModel
        statement = select(model).where(model.state == KnowledgeState.PUBLISHED.value,
            model.valid_from.is_(None) | (model.valid_from <= instant),
            model.valid_until.is_(None) | (model.valid_until > instant))
        return [self._published(row) for row in current_published_rows(self._session.scalars(statement))]

    def list_published(
        self,
        *,
        scope: KnowledgeScope | None = None,
        domain_id: str | None = None,
    ) -> list[KnowledgeEntry]:
        statement = select(KnowledgeEntryModel).where(
            KnowledgeEntryModel.state == KnowledgeState.PUBLISHED.value
        )
        if scope is not None:
            statement = statement.where(KnowledgeEntryModel.scope == scope.value)
        if domain_id is not None:
            statement = statement.where(KnowledgeEntryModel.domain_id == domain_id)
        rows = self._session.scalars(
            statement.order_by(KnowledgeEntryModel.published_at.desc())
        ).all()
        return [self._published(row) for row in current_published_rows(rows)]

    def import_published(
        self,
        *,
        entry_id: str,
        scope: KnowledgeScope,
        domain_id: str | None,
        title: str,
        content: str,
        publisher_id: str,
    ) -> KnowledgeEntry:
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        existing = self._session.get(KnowledgeEntryModel, entry_id)
        if existing is not None:
            # The maintainer edits these files in place; a rewritten section keeps
            # its identity, so the row has to follow the file. Returning early on
            # the id alone left the old text serving every recall — a rule fixed
            # in the document went on being read in its broken form.
            unchanged = (
                existing.content_hash == content_hash
                and existing.state == KnowledgeState.PUBLISHED.value
            )
            if unchanged:
                return self._published(existing)
            existing.scope = scope.value
            existing.domain_id = domain_id
            existing.title = title
            existing.content = content
            existing.content_hash = content_hash
            existing.version += 1
            existing.state = KnowledgeState.PUBLISHED.value
            existing.published_by = publisher_id
            existing.published_at = datetime.now(timezone.utc)
            self._session.flush()
            return self._published(existing)
        row = KnowledgeEntryModel(
            id=entry_id,
            scope=scope.value,
            domain_id=domain_id,
            title=title,
            content=content,
            version=1,
            content_hash=content_hash,
            source_candidate_id=None,
            state=KnowledgeState.PUBLISHED.value,
            published_by=publisher_id,
        )
        self._session.add(row)
        self._session.flush()
        return self._published(row)

    def retire_imported(self, *, title_prefix: str, keep_ids: Iterable[str]) -> int:
        """Revoke sections of an imported document that the file no longer has.

        A renamed or deleted heading changes the derived id, so re-importing adds
        the new section and leaves the old one published. Nothing ever removed it,
        and a superseded rule kept competing for recall against the rule that
        replaced it.
        """

        kept = set(keep_ids)
        rows = self._session.scalars(
            select(KnowledgeEntryModel).where(
                KnowledgeEntryModel.state == KnowledgeState.PUBLISHED.value,
                KnowledgeEntryModel.title.startswith(title_prefix),
            )
        ).all()
        retired = 0
        for row in rows:
            if row.id in kept:
                continue
            row.state = KnowledgeState.SUPERSEDED.value
            retired += 1
        if retired:
            self._session.flush()
        return retired

    @staticmethod
    def _candidate(row: KnowledgeCandidateModel) -> KnowledgeCandidate:
        return KnowledgeCandidate(
            id=row.id,
            scope=KnowledgeScope(row.scope),
            domain_id=row.domain_id,
            title=row.title,
            content=row.content,
            rationale=row.rationale,
            evidence_refs=tuple(row.evidence_refs),
            source_run_id=row.source_run_id,
            source_user_id=row.source_user_id,
            state=KnowledgeState(row.state),
            created_at=row.created_at,
            source_question=row.source_question,
            clarification_question=row.clarification_question,
            clarification_answer=row.clarification_answer,
            applicability=row.applicability,
            valid_from=_as_utc(row.valid_from),
            valid_until=_as_utc(row.valid_until),
            reviewed_by=row.reviewed_by,
            reviewed_at=row.reviewed_at,
            review_comment=row.review_comment,
        )

    @staticmethod
    def _published(row: KnowledgeEntryModel) -> KnowledgeEntry:
        return KnowledgeEntry(
            id=row.id,
            scope=KnowledgeScope(row.scope),
            domain_id=row.domain_id,
            title=row.title,
            content=row.content,
            version=row.version,
            content_hash=row.content_hash,
            source_candidate_id=row.source_candidate_id,
            state=KnowledgeState(row.state),
            published_by=row.published_by,
            published_at=row.published_at,
            applicability=row.applicability,
            valid_from=_as_utc(row.valid_from),
            valid_until=_as_utc(row.valid_until),
        )


class InMemoryKnowledgeIndex:
    def __init__(self) -> None:
        self.entries: tuple[KnowledgeEntry, ...] = ()

    def rebuild(self, published_entries: list[KnowledgeEntry]) -> int:
        self.entries = tuple(published_entries)
        return len(self.entries)
