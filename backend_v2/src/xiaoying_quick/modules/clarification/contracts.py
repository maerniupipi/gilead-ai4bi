"""Durable clarification records used by the running agent loop."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from xiaoying_quick.shared.compat import StrEnum, parse_iso_datetime


class ClarificationReason(StrEnum):
    CRITICAL_SLOT_AMBIGUITY = "critical_slot_ambiguity"
    MUTUALLY_EXCLUSIVE_DOMAINS = "mutually_exclusive_domains"
    KNOWLEDGE_CONFLICT = "knowledge_conflict"
    LOCKED_SLOT_DEVIATION = "locked_slot_deviation"


class ClarificationStatus(StrEnum):
    WAITING = "waiting"
    ANSWERED = "answered"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


@dataclass(frozen=True)
class ClarificationChoice:
    choice_id: str
    label: str
    explanation: str | None = None
    recommended: bool = False
    source: str = ""

    def __post_init__(self) -> None:
        if not self.choice_id.strip() or not self.label.strip():
            raise ValueError("clarification choice id and label are required")


@dataclass(frozen=True)
class ClarificationQuestion:
    question_id: str
    prompt: str
    reason: ClarificationReason
    choices: tuple[ClarificationChoice, ...]
    required: bool = True
    allow_free_text: bool = False
    why: str = ""
    multi_select: bool = False

    def __post_init__(self) -> None:
        if not self.question_id.strip() or not self.prompt.strip():
            raise ValueError("clarification question id and prompt are required")
        choice_ids = [choice.choice_id for choice in self.choices]
        if len(choice_ids) != len(set(choice_ids)):
            raise ValueError("clarification choice ids must be unique")
        if not self.choices and not self.allow_free_text:
            raise ValueError("clarification question needs choices or free-text support")

    def choice(self, choice_id: str) -> ClarificationChoice | None:
        return next((choice for choice in self.choices if choice.choice_id == choice_id), None)


@dataclass(frozen=True)
class ClarificationAnswer:
    question_id: str
    answered_at: datetime
    choice_id: str | None = None
    free_text: str | None = None

    def __post_init__(self) -> None:
        if not self.question_id.strip():
            raise ValueError("clarification answer needs a question id")
        if not self.choice_id and not (self.free_text and self.free_text.strip()):
            raise ValueError("clarification answer needs a choice or free text")


@dataclass(frozen=True)
class ClarificationCase:
    case_id: str
    run_id: str
    session_id: str
    frame_id: str
    status: ClarificationStatus
    questions: tuple[ClarificationQuestion, ...]
    created_at: datetime
    expires_at: datetime | None = None
    answers: tuple[ClarificationAnswer, ...] = ()
    answered_at: datetime | None = None
    superseded_plan_ids: tuple[str, ...] = ()
    topic_id: str = ""
    version: int = 1

    def __post_init__(self) -> None:
        identifiers = (self.case_id, self.run_id, self.session_id, self.frame_id)
        if any(not identifier.strip() for identifier in identifiers):
            raise ValueError("clarification case identifiers must not be blank")
        object.__setattr__(self, "topic_id", self.topic_id.strip() or self.frame_id)
        question_ids = [question.question_id for question in self.questions]
        if not question_ids or len(question_ids) != len(set(question_ids)):
            raise ValueError("clarification case needs unique questions")
        if self.version < 1:
            raise ValueError("clarification version must be positive")
        if self.status is ClarificationStatus.ANSWERED and self.answered_at is None:
            raise ValueError("answered clarification case needs answered_at")

    @classmethod
    def open(
        cls,
        *,
        case_id: str,
        run_id: str,
        session_id: str,
        frame_id: str,
        questions: tuple[ClarificationQuestion, ...],
        created_at: datetime,
        expires_at: datetime | None = None,
        superseded_plan_ids: tuple[str, ...] = (),
        topic_id: str = "",
    ) -> ClarificationCase:
        return cls(
            case_id=case_id,
            run_id=run_id,
            session_id=session_id,
            frame_id=frame_id,
            status=ClarificationStatus.WAITING,
            questions=questions,
            created_at=created_at,
            expires_at=expires_at,
            superseded_plan_ids=superseded_plan_ids,
            topic_id=topic_id,
        )

    def to_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "run_id": self.run_id,
            "session_id": self.session_id,
            "frame_id": self.frame_id,
            "topic_id": self.topic_id,
            "status": self.status.value,
            "questions": [_question_to_record(question) for question in self.questions],
            "created_at": self.created_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "answers": [_answer_to_record(answer) for answer in self.answers],
            "answered_at": self.answered_at.isoformat() if self.answered_at else None,
            "superseded_plan_ids": list(self.superseded_plan_ids),
            "version": self.version,
        }

    @classmethod
    def from_record(cls, record: Mapping[str, Any]) -> ClarificationCase:
        return cls(
            case_id=str(record["case_id"]),
            run_id=str(record["run_id"]),
            session_id=str(record["session_id"]),
            frame_id=str(record["frame_id"]),
            topic_id=str(record.get("topic_id") or record["frame_id"]),
            status=ClarificationStatus(str(record["status"])),
            questions=tuple(_question_from_record(item) for item in record.get("questions", ())),
            created_at=parse_iso_datetime(str(record["created_at"])),
            expires_at=_optional_datetime(record.get("expires_at")),
            answers=tuple(_answer_from_record(item) for item in record.get("answers", ())),
            answered_at=_optional_datetime(record.get("answered_at")),
            superseded_plan_ids=tuple(str(item) for item in record.get("superseded_plan_ids", ())),
            version=int(record.get("version", 1)),
        )


def _choice_to_record(choice: ClarificationChoice) -> dict[str, object]:
    return {
        "choice_id": choice.choice_id,
        "label": choice.label,
        "explanation": choice.explanation,
        "recommended": choice.recommended,
        "source": choice.source,
    }


def _choice_from_record(record: Mapping[str, Any]) -> ClarificationChoice:
    return ClarificationChoice(
        choice_id=str(record["choice_id"]),
        label=str(record["label"]),
        explanation=str(record["explanation"]) if record.get("explanation") else None,
        recommended=bool(record.get("recommended", False)),
        source=str(record.get("source") or ""),
    )


def _question_to_record(question: ClarificationQuestion) -> dict[str, object]:
    return {
        "question_id": question.question_id,
        "prompt": question.prompt,
        "reason": question.reason.value,
        "choices": [_choice_to_record(choice) for choice in question.choices],
        "required": question.required,
        "allow_free_text": question.allow_free_text,
        "why": question.why,
        "multi_select": question.multi_select,
    }


def _question_from_record(record: Mapping[str, Any]) -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id=str(record["question_id"]),
        prompt=str(record["prompt"]),
        reason=ClarificationReason(str(record["reason"])),
        choices=tuple(_choice_from_record(item) for item in record.get("choices", ())),
        required=bool(record.get("required", True)),
        allow_free_text=bool(record.get("allow_free_text", False)),
        why=str(record.get("why") or ""),
        multi_select=bool(record.get("multi_select", False)),
    )


def _answer_to_record(answer: ClarificationAnswer) -> dict[str, object]:
    return {
        "question_id": answer.question_id,
        "choice_id": answer.choice_id,
        "free_text": answer.free_text,
        "answered_at": answer.answered_at.isoformat(),
    }


def _answer_from_record(record: Mapping[str, Any]) -> ClarificationAnswer:
    return ClarificationAnswer(
        question_id=str(record["question_id"]),
        choice_id=str(record["choice_id"]) if record.get("choice_id") else None,
        free_text=str(record["free_text"]) if record.get("free_text") else None,
        answered_at=parse_iso_datetime(str(record["answered_at"])),
    )


def _optional_datetime(value: object) -> datetime | None:
    return None if value is None else parse_iso_datetime(str(value))


__all__ = [
    "ClarificationAnswer",
    "ClarificationCase",
    "ClarificationChoice",
    "ClarificationQuestion",
    "ClarificationReason",
    "ClarificationStatus",
]
