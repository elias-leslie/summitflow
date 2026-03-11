/**
 * Shared task configuration for priority colors, task types, and status display.
 * Used across TaskModal, TaskCard, and other task components.
 *
 * This is a barrel file — all exports come from the sibling modules:
 *   - task-config-priority.ts  (priority colors & config)
 *   - task-config-types.tsx    (task type & status config with React nodes)
 *   - task-config-utils.ts     (phase & category config)
 */

export type { PriorityColorConfig, PriorityDetailConfig } from './task-config-priority'
export {
  priorityColors,
  priorityColorClasses,
  getPriorityColors,
  getPriorityClasses,
  priorityConfig,
  PRIORITY_CONFIG,
  getPriorityConfig,
} from './task-config-priority'

export type {
  TaskTypeConfig,
  TaskTypeConfigSmall,
  TaskStatusCardConfig,
} from './task-config-types'
export {
  taskTypeConfig,
  taskTypeConfigSmall,
  getTaskTypeConfig,
  getTaskTypeConfigSmall,
  taskStatusCardConfig,
  getTaskStatusCardConfig,
  typeConfig,
  statusIconConfig,
  typeIcons,
} from './task-config-types'

export type { PhaseConfig } from './task-config-utils'
export {
  PHASE_CONFIG,
  PHASE_ICONS,
  PHASE_COLORS,
  getPhaseConfig,
  CATEGORY_COLORS,
  getCategoryColor,
} from './task-config-utils'
