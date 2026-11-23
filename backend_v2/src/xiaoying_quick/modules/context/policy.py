from __future__ import annotations

from dataclasses import dataclass, replace

from .contracts import (
    PublicationStatus,
    RecallBudget,
    RecallDecision,
    RecallHit,
    RecallLevel,
    RecallRequest,
    RecallSourceType,
)


class RecallValidationError(ValueError):
    pass


@dataclass(frozen=True)
class RecallLevelPolicy:
    level: RecallLevel
    budget: RecallBudget
    allowed_source_types: frozenset[RecallSourceType]
    min_score: float = 0.0

    def __post_init__(self) -> None:
        if not 0 <= self.min_score <= 1:
            raise ValueError("recall min_score must be between zero and one")


@dataclass(frozen=True)
class RecallPolicy:
    version: str
    levels: tuple[RecallLevelPolicy, ...]

    @classmethod
    def quick_default(cls) -> RecallPolicy:
        return cls(
            version="quick-recall-v1",
            levels=(
                RecallLevelPolicy(
                    RecallLevel.L0_RESIDENT,
                    # Sized for the routing rulebook, which is pinned here in
                    # full (~6.5k tokens) and is the reason this level exists at
                    # all: understanding is the only caller, and a rule that
                    # loses its slot is a routing error nothing downstream can
                    # recover from. The other levels stay lean.
                    RecallBudget(max_items=32, max_tokens=9_600, candidate_limit=64),
                    frozenset(
                        {
                            RecallSourceType.SESSION_STATE,
                            RecallSourceType.PERSONAL_MEMORY,
                            RecallSourceType.BUSINESS_KNOWLEDGE,
                            RecallSourceType.DOMAIN_KNOWLEDGE,
                            RecallSourceType.RUNTIME_PARAMETER,
                        }
                    ),
                    min_score=0.0,
                ),
                RecallLevelPolicy(
                    RecallLevel.L1_UNDERSTANDING,
                    RecallBudget(max_items=12, max_tokens=2_000, candidate_limit=32),
                    frozenset(
                        {
                            RecallSourceType.SESSION_STATE,
                            RecallSourceType.PERSONAL_MEMORY,
                            RecallSourceType.BUSINESS_KNOWLEDGE,
                            RecallSourceType.DOMAIN_KNOWLEDGE,
                            RecallSourceType.RUNTIME_PARAMETER,
                        }
                    ),
                    min_score=0.45,
                ),
                RecallLevelPolicy(
                    RecallLevel.L2_ATOM_DETAIL,
                    RecallBudget(max_items=10, max_tokens=2_400, candidate_limit=24),
                    frozenset(
                        {
                            RecallSourceType.BUSINESS_KNOWLEDGE,
                            RecallSourceType.DOMAIN_KNOWLEDGE,
                            RecallSourceType.LAB_CONSTRAINT,
                            RecallSourceType.SCHEMA_CARD,
                            RecallSourceType.SQL_POLICY,
                            RecallSourceType.RUNTIME_PARAMETER,
                        }
                    ),
                    min_score=0.45,
                ),
                RecallLevelPolicy(
                    RecallLevel.L3_TARGETED_RECOVERY,
                    RecallBudget(max_items=5, max_tokens=1_200, candidate_limit=12),
                    frozenset(
                        {
                            RecallSourceType.BUSINESS_KNOWLEDGE,
                            RecallSourceType.DOMAIN_KNOWLEDGE,
                            RecallSourceType.LAB_CONSTRAINT,
                            RecallSourceType.SCHEMA_CARD,
                            RecallSourceType.SQL_POLICY,
                        }
                    ),
                    min_score=0.45,
                ),
            ),
        )

    def for_level(self, level: RecallLevel) -> RecallLevelPolicy:
        policy = next((item for item in self.levels if item.level is level), None)
        if policy is None:
            raise RecallValidationError(f"no recall policy configured for {level.value}")
        return policy

    def with_budget(
        self,
        level: RecallLevel,
        *,
        max_items: int,
        max_tokens: int,
        candidate_limit: int,
    ) -> RecallPolicy:
        budget = RecallBudget(max_items, max_tokens, candidate_limit)
        changed = tuple(
            replace(item, budget=budget) if item.level is level else item for item in self.levels
        )
        if changed == self.levels:
            raise RecallValidationError(f"no recall policy configured for {level.value}")
        return replace(self, levels=changed)

    def validate_request(self, request: RecallRequest) -> RecallLevelPolicy:
        policy = self.for_level(request.level)
        if not request.request_id.strip() or not request.actor_id.strip():
            raise RecallValidationError("recall request and actor ids are required")
        if not request.session_id.strip():
            raise RecallValidationError("session id is required")
        if request.level is RecallLevel.L1_UNDERSTANDING:
            if not request.frame_id or not request.query.strip():
                raise RecallValidationError("L1 recall requires a query frame and query")
        elif request.level is RecallLevel.L2_ATOM_DETAIL:
            if (
                not request.frame_id
                or not request.atom_id
                or not request.domain_ids
                or not request.query.strip()
            ):
                raise RecallValidationError(
                    "L2 recall requires frame, atom, selected domain and query"
                )
        elif request.level is RecallLevel.L3_TARGETED_RECOVERY:
            if (
                not request.frame_id
                or not request.atom_id
                or not request.domain_ids
                or not request.failure_code
                or not request.target_refs
                or not request.query.strip()
            ):
                raise RecallValidationError(
                    "L3 recall requires an atom, failure code and targeted references"
                )
        return policy

    def authorize(
        self,
        request: RecallRequest,
        hit: RecallHit,
        level_policy: RecallLevelPolicy,
    ) -> RecallDecision:
        allowed = level_policy.allowed_source_types
        if request.allowed_source_types is not None:
            allowed = allowed.intersection(request.allowed_source_types)
        if hit.source_type not in allowed:
            return RecallDecision.DENIED_SOURCE
        if (
            request.level is RecallLevel.L0_RESIDENT
            and not hit.is_summary
            and not hit.resident_verbatim
        ):
            return RecallDecision.DENIED_NOT_SUMMARY
        if hit.from_session_patch:
            if hit.session_id != request.session_id:
                return RecallDecision.DENIED_SESSION
            if not request.topic_id or hit.topic_id != request.topic_id:
                return RecallDecision.DENIED_TOPIC
            return RecallDecision.SELECTED
        if hit.source_type is RecallSourceType.SESSION_STATE:
            if hit.session_id != request.session_id:
                return RecallDecision.DENIED_SESSION
        elif hit.source_type is RecallSourceType.PERSONAL_MEMORY:
            if hit.owner_id != request.actor_id:
                return RecallDecision.DENIED_OWNER
            if hit.publication_status not in {
                PublicationStatus.PRIVATE,
                PublicationStatus.PUBLISHED,
            }:
                return RecallDecision.DENIED_UNPUBLISHED
        elif hit.source_type in {
            RecallSourceType.BUSINESS_KNOWLEDGE,
            RecallSourceType.DOMAIN_KNOWLEDGE,
            RecallSourceType.LAB_CONSTRAINT,
            RecallSourceType.SCHEMA_CARD,
            RecallSourceType.SQL_POLICY,
        }:
            if hit.publication_status is not PublicationStatus.PUBLISHED:
                return RecallDecision.DENIED_UNPUBLISHED
        if hit.score < level_policy.min_score:
            return RecallDecision.DENIED_LOW_RELEVANCE
        return RecallDecision.SELECTED
