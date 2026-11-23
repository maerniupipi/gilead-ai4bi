from __future__ import annotations

from datetime import datetime

from .contracts import (
    ContextPack,
    RecallDecision,
    RecallHit,
    RecallReceipt,
    RecallReceiptEntry,
    RecallRequest,
    RecallSourceType,
)
from .policy import RecallPolicy
from .ports import RecallSourcePort


class ContextBroker:
    """Applies deterministic ACL and token budgets around an injected search adapter."""

    def __init__(self, *, source: RecallSourcePort, policy: RecallPolicy) -> None:
        self._source = source
        self._policy = policy

    def recall(self, request: RecallRequest, *, performed_at: datetime) -> ContextPack:
        level_policy = self._policy.validate_request(request)
        hits = tuple(
            self._source.search(
                request,
                candidate_limit=level_policy.budget.candidate_limit,
            )
        )
        ordered = sorted(
            hits,
            key=lambda hit: (-hit.score, hit.content_id, hit.section_id, hit.version),
        )
        selected: list[RecallHit] = []
        entries: list[RecallReceiptEntry] = []
        total_tokens = 0

        for hit in ordered:
            decision = self._policy.authorize(request, hit, level_policy)
            if decision is RecallDecision.SELECTED:
                over_items = len(selected) >= level_policy.budget.max_items
                over_tokens = total_tokens + hit.token_count > level_policy.budget.max_tokens
                if over_items or over_tokens:
                    decision = RecallDecision.DENIED_BUDGET
                else:
                    selected.append(hit)
                    total_tokens += hit.token_count
            entries.append(_receipt_entry(hit, decision))

        receipt = RecallReceipt(
            receipt_id=f"recall:{request.request_id}",
            request_id=request.request_id,
            level=request.level,
            actor_id=request.actor_id,
            session_id=request.session_id,
            topic_id=request.topic_id,
            frame_id=request.frame_id,
            atom_id=request.atom_id,
            performed_at=performed_at,
            policy_version=self._policy.version,
            entries=tuple(entries),
            total_tokens=total_tokens,
            selected_count=len(selected),
            target_refs=request.target_refs,
            failure_code=request.failure_code,
        )
        return ContextPack(level=request.level, items=tuple(selected), receipt=receipt)


def _receipt_entry(hit: RecallHit, decision: RecallDecision) -> RecallReceiptEntry:
    is_public = hit.source_type in {
        RecallSourceType.BUSINESS_KNOWLEDGE,
        RecallSourceType.DOMAIN_KNOWLEDGE,
    }
    rejected_reason = hit.rejected_reason
    if decision is not RecallDecision.SELECTED and not rejected_reason:
        rejected_reason = decision.value
    return RecallReceiptEntry(
        source_type=hit.source_type,
        owner_id=hit.owner_id,
        topic_id=hit.topic_id,
        content_id=hit.content_id,
        section_id=hit.section_id,
        version=hit.version,
        content_hash=hit.content_hash,
        match_method=hit.match_method,
        score=hit.score,
        matched_reason=hit.matched_reason,
        rejected_reason=rejected_reason,
        decision=decision,
        token_count=hit.token_count,
        from_session_patch=hit.from_session_patch,
        is_personal=hit.source_type is RecallSourceType.PERSONAL_MEMORY,
        is_published_public_knowledge=is_public and hit.publication_status.value == "published",
        acl_tags=hit.acl_tags,
    )
