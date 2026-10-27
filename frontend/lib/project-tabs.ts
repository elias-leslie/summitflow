export const PROJECT_TABS = ['tasks'] as const
export type ProjectTab = (typeof PROJECT_TABS)[number]

export function parseProjectTab(value: string | null): ProjectTab | null {
  if (!value) return null
  return PROJECT_TABS.includes(value as ProjectTab)
    ? (value as ProjectTab)
    : null
}
