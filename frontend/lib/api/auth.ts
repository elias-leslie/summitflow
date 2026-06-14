import { fetchWithErrorHandling, postJson, putJson } from './utils'

export type SummitFlowRole = 'owner' | 'viewer' | 'none'
export type ShareSection = 'design'

export interface AuthGrant {
  project_id: string
  section: ShareSection
  created_at?: string | null
}

export interface AuthMe {
  authenticated: boolean
  email: string | null
  role: SummitFlowRole | string
  is_owner: boolean
  is_viewer: boolean
  is_local_bypass: boolean
  grants: AuthGrant[]
}

export interface ShareUser {
  email: string
  role: 'owner' | 'viewer'
  is_active: boolean
  created_at: string
  updated_at: string
  grants: AuthGrant[]
}

export function fetchAuthMe(): Promise<AuthMe> {
  return fetchWithErrorHandling<AuthMe>('/api/auth/me', {
    errorMessage: 'Failed to fetch current user',
  })
}

export function fetchShareUsers(): Promise<ShareUser[]> {
  return fetchWithErrorHandling<ShareUser[]>('/api/auth/users', {
    errorMessage: 'Failed to fetch shared users',
  })
}

export function upsertShareUser(data: {
  email: string
  role?: 'owner' | 'viewer'
  is_active?: boolean
}): Promise<ShareUser> {
  return postJson<ShareUser>('/api/auth/users', data, 'Failed to save user')
}

export function deleteShareUser(email: string): Promise<{ status: string }> {
  return fetchWithErrorHandling<{ status: string }>(
    `/api/auth/users/${encodeURIComponent(email)}`,
    {
      method: 'DELETE',
      errorMessage: 'Failed to delete user',
    },
  )
}

export function setShareUserProjectGrants(
  email: string,
  projectId: string,
  sections: ShareSection[],
): Promise<AuthGrant[]> {
  return putJson<AuthGrant[]>(
    `/api/auth/users/${encodeURIComponent(email)}/grants`,
    { project_id: projectId, sections },
    'Failed to save sharing permissions',
  )
}
