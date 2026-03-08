/**
 * Tasks API - Type Definitions
 *
 * This barrel file re-exports all task-related types from focused sub-modules:
 * - tasks-types-core.ts:       Core task types (Task, TaskStatus, etc.)
 * - tasks-types-enrichment.ts: Enrichment workflow types (Subtask, Step, etc.)
 * - tasks-types-execution.ts:  Execution & batch types
 * - tasks-types-agenthub.ts:   Agent Hub observability types
 */

// ============================================================================
// Core Task Types
// ============================================================================

export type {
  TaskStatus,
  TaskType,
  AgentType,
  EnrichmentStatus,
  TaskAcceptanceCriterion,
  CapabilityContext,
  BlockerInfo,
  WorktreeInfo,
  Task,
  TaskListResponse,
  TaskDependency,
} from './tasks-types-core'

// ============================================================================
// Enrichment Types
// ============================================================================

export type {
  Step,
  StepSummary,
  Subtask,
  SubtasksResponse,
  EnrichmentRequest,
  CleanupPromptResponse,
  DiscussionMessage,
  DiscussionResponse,
  CriterionVerifyRequest,
  CriterionVerifyResponse,
} from './tasks-types-enrichment'

// ============================================================================
// Execution Types
// ============================================================================

export type {
  ExecuteTaskOptions,
  ExecuteTaskResponse,
  BatchTaskCreateItem,
  BatchTaskResult,
  BatchTaskResponse,
  DeleteTaskResponse,
} from './tasks-types-execution'

// ============================================================================
// Agent Hub Types
// ============================================================================

export type {
  CodingAgent,
  CodingAgentsResponse,
  AgentEventType,
  AgentHubEvent,
  AgentHubLiveActivity,
  AgentHubSessionSummary,
  AgentHubEventsResponse,
} from './tasks-types-agenthub'
