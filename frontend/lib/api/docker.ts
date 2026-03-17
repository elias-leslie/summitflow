/**
 * Compatibility adapter for the legacy Docker runtime imports.
 * The canonical client naming is now `runtimeApi`.
 */

import type {
  RuntimeActionResult,
  RuntimeModeStatus,
  RuntimeServiceMetrics,
  RuntimeServiceStatus,
} from './runtime'

export { runtimeApi, runtimeApi as dockerApi } from './runtime'
export type {
  HealthSummary,
  ProxmoxGuestStatus,
  ProxmoxNodeStatus,
  ProxmoxStatus,
  RuntimeActionResult,
  RuntimeModeStatus,
  RuntimeServiceMetrics,
  RuntimeServiceStatus,
} from './runtime'

export type ContainerStatus = RuntimeServiceStatus
export type ContainerMetrics = RuntimeServiceMetrics
export type ActionResult = RuntimeActionResult
export type DockerRuntimeStatus = RuntimeModeStatus
