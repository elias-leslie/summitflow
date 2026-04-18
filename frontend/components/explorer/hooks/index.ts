/**
 * Explorer Hooks - Public exports
 *
 * Four hooks with clear separation of concerns:
 * - useExplorerData: Data fetching with react-query
 * - useExplorerState: UI state (expanded, selected)
 * - useExplorerFilters: Filter/sort state
 * - useDedupedDependencies: Dependency deduplication by package name
 */

export {
  type DedupedDependency,
  useDedupedDependencies,
} from './useDedupedDependencies'
export {
  explorerKeys,
  useExplorerChildren,
  useExplorerData,
} from './useExplorerData'
export { useExplorerFilters } from './useExplorerFilters'
export { useExplorerState } from './useExplorerState'
export {
  explorerSymbolKeys,
  useExplorerSymbolDetail,
  useExplorerSymbolSearch,
} from './useExplorerSymbolSearch'
