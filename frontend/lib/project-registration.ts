export interface ProjectFormFields {
  name: string
  projectId?: string
  baseUrl: string
  healthEndpoint: string
  rootPath: string
}

export interface ProjectFormErrors {
  name?: string
  projectId?: string
  baseUrl?: string
  healthEndpoint?: string
  rootPath?: string
}

export const DEFAULT_HEALTH_ENDPOINT = '/health'

export function buildHostedBaseUrl(projectId: string): string {
  const normalized = normalizeProjectId(projectId)
  return normalized ? `https://${normalized}.summitflow.dev` : ''
}

export function buildHostedRootPath(projectId: string): string {
  const normalized = normalizeProjectId(projectId)
  return normalized ? `/srv/workspaces/projects/${normalized}` : ''
}

export function normalizeProjectId(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9\s-]/g, '')
    .replace(/\s+/g, '-')
    .replace(/-+/g, '-')
    .replace(/^-|-$/g, '')
    .slice(0, 50)
}

export function normalizeBaseUrl(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

export function normalizeHealthEndpoint(value: string): string {
  const trimmed = value.trim()
  if (!trimmed) return ''
  if (/^https?:\/\//.test(trimmed)) {
    return trimmed.replace(/\/+$/, '')
  }

  return `/${trimmed.replace(/^\/+/, '')}`
}

export function normalizeRootPath(value: string): string {
  return value.trim().replace(/\/+$/, '')
}

export function buildHealthPreview(
  baseUrl: string,
  healthEndpoint: string,
): string {
  const normalizedBaseUrl = normalizeBaseUrl(baseUrl)
  const normalizedHealthEndpoint = normalizeHealthEndpoint(healthEndpoint)

  if (!normalizedHealthEndpoint) {
    return 'Disabled'
  }

  if (normalizedHealthEndpoint.startsWith('http')) {
    return normalizedHealthEndpoint
  }

  return normalizedBaseUrl
    ? `${normalizedBaseUrl}${normalizedHealthEndpoint}`
    : normalizedHealthEndpoint
}

export function validateProjectForm(
  fields: ProjectFormFields,
  options: { requireProjectId?: boolean } = {},
): ProjectFormErrors {
  const errors: ProjectFormErrors = {}
  const requireProjectId = options.requireProjectId ?? true
  const normalizedProjectId = normalizeProjectId(fields.projectId ?? '')
  const normalizedBaseUrl = normalizeBaseUrl(fields.baseUrl)
  const normalizedHealthEndpoint = normalizeHealthEndpoint(fields.healthEndpoint)
  const normalizedRootPath = normalizeRootPath(fields.rootPath)

  if (!fields.name.trim()) {
    errors.name = 'Project name is required'
  }

  if (requireProjectId) {
    if (!normalizedProjectId) {
      errors.projectId = 'Project ID is required'
    } else if (!/^[a-z0-9-]+$/.test(normalizedProjectId)) {
      errors.projectId = 'Project ID must be lowercase alphanumeric with hyphens'
    }
  }

  if (!normalizedBaseUrl) {
    errors.baseUrl = 'Base URL is required'
  } else {
    try {
      const parsed = new URL(normalizedBaseUrl)
      if (!['http:', 'https:'].includes(parsed.protocol)) {
        errors.baseUrl = 'URL must use http or https'
      }
    } catch {
      errors.baseUrl = 'Invalid URL format'
    }
  }

  if (
    normalizedHealthEndpoint &&
    !normalizedHealthEndpoint.startsWith('/') &&
    !/^https?:\/\//.test(normalizedHealthEndpoint)
  ) {
    errors.healthEndpoint = 'Health endpoint must start with / or be a full URL'
  }

  if (normalizedRootPath && !normalizedRootPath.startsWith('/')) {
    errors.rootPath = 'Root path must be an absolute path'
  }

  return errors
}

export interface NormalizedProjectFormValues {
  name: string
  projectId?: string
  baseUrl: string
  healthEndpoint: string
  rootPath: string
}

export function normalizeProjectFormValues(
  fields: ProjectFormFields,
): NormalizedProjectFormValues {
  return {
    name: fields.name.trim(),
    projectId: fields.projectId ? normalizeProjectId(fields.projectId) : undefined,
    baseUrl: normalizeBaseUrl(fields.baseUrl),
    healthEndpoint:
      normalizeHealthEndpoint(fields.healthEndpoint) || DEFAULT_HEALTH_ENDPOINT,
    rootPath: normalizeRootPath(fields.rootPath),
  }
}
