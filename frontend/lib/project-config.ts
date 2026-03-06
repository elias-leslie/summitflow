export const DEFAULT_PROJECT_ID = 'summitflow'

export function getProjectIdOrDefault(projectId?: string | null): string {
  return projectId?.trim() || DEFAULT_PROJECT_ID
}

export function getProjectMemoryGroupPrefix(projectId?: string | null): string {
  return `${getProjectIdOrDefault(projectId)}:`
}
