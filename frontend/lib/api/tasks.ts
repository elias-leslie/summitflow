/**
 * Tasks API - Main barrel export
 *
 * This module provides a unified interface to all task-related functionality.
 * Implementation has been split into focused modules for better maintainability:
 *
 * - tasks-types.ts: Type definitions
 * - tasks-crud.ts: Core CRUD operations
 * - tasks-enrichment.ts: Enrichment workflow (subtasks, steps, criteria)
 * - tasks-execution.ts: Autonomous execution and batch operations
 * - tasks-observability.ts: Agent Hub integration and observability
 */

// ============================================================================
// Type Exports
// ============================================================================

export type {
  // Core task types
  TaskStatus,
  TaskType,
  AgentType,
  Task,
  TaskListResponse,
  TaskDependency,
  // Acceptance criteria
  TaskAcceptanceCriterion,
  // Capability & blocking
  CapabilityContext,
  BlockerInfo,
  WorktreeInfo,
  VerificationResult,
  // Enrichment types
  EnrichmentStatus,
  EnrichmentRequest,
  DiscussionMessage,
  DiscussionResponse,
  // Subtasks & steps
  Subtask,
  SubtasksResponse,
  Step,
  StepSummary,
  // Execution types
  ExecuteTaskOptions,
  ExecuteTaskResponse,
  BatchTaskCreateItem,
  BatchTaskResult,
  BatchTaskResponse,
  DeleteTaskResponse,
  // Agent Hub types
  CodingAgent,
  CodingAgentsResponse,
  AgentEventType,
  AgentHubEvent,
  AgentHubLiveActivity,
  AgentHubSessionSummary,
  AgentHubEventsResponse,
  NarrationTagType,
  NarrationTag,
  NarrationTimelineResponse,
} from './tasks-types'

// ============================================================================
// CRUD Operations
// ============================================================================

export {
  // Create & update
  createTask,
  updateTask,
  // Read operations
  fetchTask,
  fetchTasks,
  fetchBlockedTasks,
  // Execution control
  startTask,
  updateTaskStatus,
  // Delete operations
  deleteTask,
  deleteTasks,
} from './tasks-crud'

// ============================================================================
// Enrichment & Refinement
// ============================================================================

export {
  // Enrichment workflow
  enrichTask,
  discussTask,
  acceptTask,
  // Subtasks
  getSubtasks,
  getSubtasksWithSteps,
  updateSubtask,
  // Steps
  getSteps,
  updateStep,
} from './tasks-enrichment'

// ============================================================================
// Execution & Batch Operations
// ============================================================================

export {
  // Autonomous execution
  executeTask,
  // Batch operations
  batchCreateTasks,
} from './tasks-execution'

// ============================================================================
// Agent Hub Integration
// ============================================================================

export {
  // Coding agents
  fetchCodingAgents,
  // Observability
  fetchTaskAgentEvents,
  // Narration
  fetchNarrationTimeline,
} from './tasks-observability'
