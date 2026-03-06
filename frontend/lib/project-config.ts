export const DEFAULT_PROJECT_ID = 'summitflow'

export function getProjectMemoryGroupPrefix(projectId: string): string {
  return `${projectId}:`
}
