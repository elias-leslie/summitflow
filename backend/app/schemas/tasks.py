"""Task-related Pydantic models for request/response validation.

Extracted from app/api/tasks.py for reuse across the codebase.

This module re-exports all task schemas from their dedicated modules
for backward compatibility.
"""

# Base CRUD schemas
from .task_base import (
    ClaimTaskRequest,
    StartTaskRequest,
    TaskCreate,
    TaskListResponse,
    TaskLogEntry,
    TaskResponse,
    TaskStatusUpdate,
    TaskUpdate,
    ValidationResultResponse,
)

# Batch operations
from .task_batch import (
    BatchTaskCreate,
    BatchTaskRequest,
    BatchTaskResponse,
    BatchTaskResult,
)

# Citations
from .task_citations import (
    CitationAcknowledgeRequest,
    CitationAcknowledgeResponse,
    CitationLogRequest,
    CitationLogResponse,
)

# Acceptance criteria
from .task_criteria import (
    AcceptanceCriterion,
    CreateTaskCriterionRequest,
    UpdateTaskCriterionRequest,
    VerifyTaskCriterionRequest,
)

# Dependencies
from .task_dependencies import (
    DependencyCreate,
    DependencyResponse,
)

# AI enrichment
from .task_enrichment import (
    BlockerInfo,
    CapabilityContext,
    CleanupPromptRequest,
    CleanupPromptResponse,
    DiscussionMessage,
    DiscussionRequest,
    DiscussionResponse,
    EnrichmentRequest,
    EnrichmentResponse,
)

# Ideation agent
from .task_ideation import (
    IdeationTaskCreate,
    IdeationTaskResponse,
)

# Subtasks
from .task_subtasks import (
    StepInput,
    SubtaskCreate,
    SubtaskResponse,
    SubtaskSummary,
    SubtaskUpdate,
)

# Rebuild models with forward references now that all types are imported
TaskResponse.model_rebuild()
TaskCreate.model_rebuild()
TaskUpdate.model_rebuild()
BatchTaskResponse.model_rebuild()
CapabilityContext.model_rebuild()
DiscussionResponse.model_rebuild()

__all__ = [
    # Acceptance criteria
    "AcceptanceCriterion",
    # Batch operations
    "BatchTaskCreate",
    "BatchTaskRequest",
    "BatchTaskResponse",
    "BatchTaskResult",
    # AI enrichment
    "BlockerInfo",
    "CapabilityContext",
    # Citations
    "CitationAcknowledgeRequest",
    "CitationAcknowledgeResponse",
    "CitationLogRequest",
    "CitationLogResponse",
    # Base CRUD
    "ClaimTaskRequest",
    "CleanupPromptRequest",
    "CleanupPromptResponse",
    "CreateTaskCriterionRequest",
    # Dependencies
    "DependencyCreate",
    "DependencyResponse",
    "DiscussionMessage",
    "DiscussionRequest",
    "DiscussionResponse",
    "EnrichmentRequest",
    "EnrichmentResponse",
    # Ideation agent
    "IdeationTaskCreate",
    "IdeationTaskResponse",
    "StartTaskRequest",
    # Subtasks
    "StepInput",
    "SubtaskCreate",
    "SubtaskResponse",
    "SubtaskSummary",
    "SubtaskUpdate",
    "TaskCreate",
    "TaskListResponse",
    "TaskLogEntry",
    "TaskResponse",
    "TaskStatusUpdate",
    "TaskUpdate",
    "UpdateTaskCriterionRequest",
    "ValidationResultResponse",
    "VerifyTaskCriterionRequest",
]
