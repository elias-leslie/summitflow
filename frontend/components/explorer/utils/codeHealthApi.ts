/**
 * API functions for code health monitoring
 *
 * Re-exports from @/lib/api/explorer-analysis for backwards compatibility.
 */

export type {
  RefactorTarget,
  RefactorTargetsResponse,
  CoverageGapsResponse,
  CoverageGapsSummary,
} from '@/lib/api/explorer-analysis'

export { fetchRefactorTargets, fetchCoverageGaps } from '@/lib/api/explorer-analysis'
