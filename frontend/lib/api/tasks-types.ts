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
  BlockerInfo,
  CapabilityContext,
  EnrichmentStatus,
  Task,
  TaskAcceptanceCriterion,
  TaskDependency,
  TaskListResponse,
  TaskStatus,
  TaskType,
  VerificationResult,
} from './tasks-types-core'

// ============================================================================
// Enrichment Types
// ============================================================================

export type {
  DiscussionMessage,
  DiscussionResponse,
  Step,
  StepSummary,
  Subtask,
  SubtasksResponse,
} from './tasks-types-enrichment'

// ============================================================================
// Execution Types
// ============================================================================

export type {
  DeleteTaskResponse,
  ExecuteTaskOptions,
  ExecuteTaskResponse,
} from './tasks-types-execution'

// ============================================================================
// Agent Hub Types
// ============================================================================

export type {
  AgentEventType,
  AgentHubEvent,
  AgentHubEventsResponse,
  AgentHubLiveActivity,
  AgentHubSessionSummary,
  CodingAgent,
  CodingAgentsResponse,
  NarrationTag,
  NarrationTagType,
  NarrationTimelineResponse,
} from './tasks-types-agenthub'
