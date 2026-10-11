import { fetchWithErrorHandling } from './utils'

export interface AuthMe {
  authenticated: boolean
  email: string | null
  role: string
  is_owner: boolean
  is_local_bypass: boolean
}

export function fetchAuthMe(): Promise<AuthMe> {
  return fetchWithErrorHandling<AuthMe>('/api/auth/me', {
    errorMessage: 'Failed to fetch current user',
  })
}
