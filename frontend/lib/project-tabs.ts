import type { ExplorerType } from '@/components/explorer/types'

export const PROJECT_TABS = ['tasks', 'explorer'] as const
export type ProjectTab = (typeof PROJECT_TABS)[number]

const EXPLORER_TYPES: ExplorerType[] = [
  'files',
  'database',
  'tasks',
  'api',
  'pages',
  'dependencies',
  'architecture',
]

export function parseProjectTab(value: string | null): ProjectTab | null {
  if (!value) return null
  return PROJECT_TABS.includes(value as ProjectTab)
    ? (value as ProjectTab)
    : null
}

export function parseExplorerType(value: string | null): ExplorerType {
  if (!value) return 'files'
  return EXPLORER_TYPES.includes(value as ExplorerType)
    ? (value as ExplorerType)
    : 'files'
}
