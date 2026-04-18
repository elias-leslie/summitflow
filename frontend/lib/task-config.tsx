/**
 * Shared task configuration for priority colors, task types, and status display.
 * Used across TaskModal, TaskCard, and other task components.
 *
 * This is a barrel file — all exports come from the sibling modules:
 *   - task-config-priority.ts  (priority colors & config)
 *   - task-config-types.tsx    (task type & status config with React nodes)
 *   - task-config-utils.ts     (phase & category config)
 */

export type {
  PriorityColorConfig,
  PriorityDetailConfig,
} from './task-config-priority'
export {
  getPriorityClasses,
  getPriorityColors,
  getPriorityConfig,
  PRIORITY_CONFIG,
  priorityColorClasses,
  priorityColors,
  priorityConfig,
} from './task-config-priority'

export type {
  TaskStatusCardConfig,
  TaskTypeConfig,
  TaskTypeConfigSmall,
} from './task-config-types'
export {
  getTaskStatusCardConfig,
  getTaskTypeConfig,
  getTaskTypeConfigSmall,
  statusIconConfig,
  taskStatusCardConfig,
  taskTypeConfig,
  taskTypeConfigSmall,
  typeConfig,
  typeIcons,
} from './task-config-types'

export type { PhaseConfig } from './task-config-utils'
export {
  CATEGORY_COLORS,
  getCategoryColor,
  getPhaseConfig,
  PHASE_COLORS,
  PHASE_CONFIG,
  PHASE_ICONS,
} from './task-config-utils'
