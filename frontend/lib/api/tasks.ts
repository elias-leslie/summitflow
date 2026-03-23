/**
 * Tasks API - Main barrel export
 *
 * This module provides a unified interface to all task-related functionality.
 * Implementation has been split into focused modules for better maintainability:
 *
 * - tasks-types.ts: Type definitions
 * - tasks-crud.ts: Core CRUD operations and execution
 * - tasks-enrichment.ts: Enrichment workflow (subtasks, steps, criteria)
 * - tasks-observability.ts: Agent Hub integration and observability
 */

// ============================================================================
// Type Exports
// ============================================================================

export type {
  // Core task types
  TaskStatus,
  TaskType,
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
  // Execution control
  executeTask,
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
