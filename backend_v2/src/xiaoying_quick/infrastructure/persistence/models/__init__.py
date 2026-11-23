"""Import all ORM models so metadata contains the complete schema."""

from xiaoying_quick.infrastructure.persistence.models.agent_configs import AgentConfigModel
from xiaoying_quick.infrastructure.persistence.models.artifacts import (
    DatasetEvidenceModel,
    FactModel,
    RunArtifactModel,
)
from xiaoying_quick.infrastructure.persistence.models.branding import WorkspaceBrandingModel
from xiaoying_quick.infrastructure.persistence.models.chat import (
    ChatMessageModel,
    ChatSessionModel,
    ClarificationCaseModel,
    SessionDomainPatchModel,
)
from xiaoying_quick.infrastructure.persistence.models.data_sources import (
    AuditEventModel,
    DataSourceModel,
    DataSourceRevisionModel,
    DomainBindingModel,
    SchemaSnapshotModel,
    SourceLabModel,
)
from xiaoying_quick.infrastructure.persistence.models.eval_results import (
    EvalBatchModel,
    EvalResultModel,
)
from xiaoying_quick.infrastructure.persistence.models.feedback import AnswerFeedbackModel
from xiaoying_quick.infrastructure.persistence.models.identity import (
    IdentityDataScopeModel,
    IdentityUserModel,
)
from xiaoying_quick.infrastructure.persistence.models.jobs import QuickJobModel
from xiaoying_quick.infrastructure.persistence.models.knowledge import (
    KnowledgeCandidateModel,
    KnowledgeEntryModel,
    PersonalMemoryModel,
    PersonalMemoryRevisionModel,
)
from xiaoying_quick.infrastructure.persistence.models.lab_connection import LabConnectionModel
from xiaoying_quick.infrastructure.persistence.models.model_configs import ModelConfigModel
from xiaoying_quick.infrastructure.persistence.models.runs import RunEventModel, RunModel
from xiaoying_quick.infrastructure.persistence.models.skill_packs import SkillPackModel
from xiaoying_quick.infrastructure.persistence.models.usage import UsageEventModel

__all__ = [
    "AgentConfigModel",
    "AuditEventModel",
    "DataSourceModel",
    "DataSourceRevisionModel",
    "DatasetEvidenceModel",
    "DomainBindingModel",
    "EvalBatchModel",
    "EvalResultModel",
    "AnswerFeedbackModel",
    "FactModel",
    "IdentityUserModel",
    "IdentityDataScopeModel",
    "ChatMessageModel",
    "ChatSessionModel",
    "ClarificationCaseModel",
    "KnowledgeCandidateModel",
    "KnowledgeEntryModel",
    "ModelConfigModel",
    "LabConnectionModel",
    "PersonalMemoryModel",
    "PersonalMemoryRevisionModel",
    "QuickJobModel",
    "RunArtifactModel",
    "RunEventModel",
    "RunModel",
    "SchemaSnapshotModel",
    "SessionDomainPatchModel",
    "SkillPackModel",
    "SourceLabModel",
    "UsageEventModel",
    "WorkspaceBrandingModel",
]
