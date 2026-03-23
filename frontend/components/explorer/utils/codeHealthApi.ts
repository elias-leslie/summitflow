/**
 * API functions for code health monitoring
 *
 * Re-exports from @/lib/api/explorer-analysis for backwards compatibility.
 */

export type {
  RefactorTarget,
  RefactorTargetsResponse,
} from '@/lib/api/explorer-analysis'

export { fetchRefactorTargets } from '@/lib/api/explorer-analysis'
