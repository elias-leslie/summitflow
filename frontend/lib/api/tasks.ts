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
  CriterionVerifyRequest,
  CriterionVerifyResponse,
  // Capability & blocking
  CapabilityContext,
  BlockerInfo,
  WorktreeInfo,
  // Enrichment types
  EnrichmentStatus,
  EnrichmentRequest,
  CleanupPromptResponse,
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
  AgentHubEventsResponse,
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
  fetchReadyTasks,
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
  cleanupPrompt,
  discussTask,
  acceptTask,
  // Subtasks
  getSubtasks,
  getSubtasksWithSteps,
  updateSubtask,
  // Steps
  getSteps,
  updateStep,
  getStepSummary,
  // Acceptance criteria
  getTaskCriteria,
  verifyTaskCriterion,
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
} from './tasks-observability'
