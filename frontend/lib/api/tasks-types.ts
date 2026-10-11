/**
 * Tasks API - Type Definitions
 *
 * This barrel file re-exports all task-related types from focused sub-modules:
 * - tasks-types-core.ts:       Core task types (Task, TaskStatus, etc.)
 * - tasks-types-subtasks.ts:   Subtask and step types
 * - tasks-types-execution.ts:  Delete response types
 * - tasks-types-agenthub.ts:   Agent Hub observability types
 */

// ============================================================================
// Core Task Types
// ============================================================================

export type {
  BlockerInfo,
  CapabilityContext,
  Task,
  TaskAcceptanceCriterion,
  TaskDependency,
  TaskListResponse,
  TaskStatus,
  TaskType,
  VerificationResult,
} from './tasks-types-core'

// ============================================================================
// Subtask Types
// ============================================================================

export type {
  Step,
  StepSummary,
  Subtask,
  SubtasksResponse,
} from './tasks-types-subtasks'

// ============================================================================
// Delete Types
// ============================================================================

export type { DeleteTaskResponse } from './tasks-types-execution'

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
