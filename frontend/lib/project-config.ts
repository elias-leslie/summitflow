export const DEFAULT_PROJECT_ID = 'summitflow'

const RESERVED_PROJECT_ROUTE_IDS = new Set(['new'])

export function getRouteProjectId(projectId?: string | null): string | null {
  const normalized = projectId?.trim()
  if (!normalized || RESERVED_PROJECT_ROUTE_IDS.has(normalized)) {
    return null
  }
  return normalized
}

export function getProjectIdFromPathname(
  pathname?: string | null,
): string | null {
  if (!pathname) {
    return null
  }
  const match = pathname.match(/^\/projects\/([^/]+)/)
  return getRouteProjectId(match?.[1] ?? null)
}

export function getProjectIdOrDefault(projectId?: string | null): string {
  return getRouteProjectId(projectId) ?? DEFAULT_PROJECT_ID
}

export function getProjectMemoryGroupPrefix(projectId?: string | null): string {
  return `${getProjectIdOrDefault(projectId)}:`
}
