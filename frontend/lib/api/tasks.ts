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
  AgentEventType,
  AgentHubEvent,
  AgentHubEventsResponse,
  AgentHubLiveActivity,
  AgentHubSessionSummary,
  BlockerInfo,
  // Capability & blocking
  CapabilityContext,
  // Agent Hub types
  CodingAgent,
  CodingAgentsResponse,
  DeleteTaskResponse,
  DiscussionMessage,
  DiscussionResponse,
  // Enrichment types
  EnrichmentStatus,
  // Execution types
  ExecuteTaskOptions,
  ExecuteTaskResponse,
  NarrationTag,
  NarrationTagType,
  NarrationTimelineResponse,
  Step,
  StepSummary,
  // Subtasks & steps
  Subtask,
  SubtasksResponse,
  Task,
  // Acceptance criteria
  TaskAcceptanceCriterion,
  TaskDependency,
  TaskListResponse,
  // Core task types
  TaskStatus,
  TaskType,
  VerificationResult,
} from './tasks-types'

// ============================================================================
// CRUD Operations
// ============================================================================

export {
  // Create & update
  createTask,
  // Delete operations
  deleteTask,
  deleteTasks,
  // Execution control
  executeTask,
  // Read operations
  fetchTask,
  fetchTasks,
  updateTask,
  updateTaskStatus,
} from './tasks-crud'

// ============================================================================
// Enrichment & Refinement
// ============================================================================

export {
  acceptTask,
  // Enrichment workflow
  discussTask,
  // Steps
  getSteps,
  // Subtasks
  getSubtasks,
  getSubtasksWithSteps,
  updateStep,
  updateSubtask,
} from './tasks-enrichment'

// ============================================================================
// Agent Hub Integration
// ============================================================================

export {
  // Coding agents
  fetchCodingAgents,
  // Narration
  fetchNarrationTimeline,
  // Observability
  fetchTaskAgentEvents,
} from './tasks-observability'
