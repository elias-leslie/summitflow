import { useQuery } from '@tanstack/react-query'
import { fetchWithErrorHandling } from '@/lib/api/utils'
import { POLL_SLOW } from '@/lib/polling'

/**
 * Fetches all project permission tiers from Agent Hub (via proxy)
 * and returns the tier for a specific project.
 *
 * Uses a shared query key so multiple sidebar items share the same fetch.
 */

interface ProjectPermission {
  project_id: string
  permission_tier: 'off' | 'read' | 'write' | 'yolo'
  auto_exec_enabled: boolean
}

async function fetchPermissions(): Promise<ProjectPermission[]> {
  try {
    return await fetchWithErrorHandling<ProjectPermission[]>(
      '/api/agent-hub/projects/permissions',
      { errorMessage: 'Failed to fetch project permissions' },
    )
  } catch {
    // Silent degradation — sidebar shows no tier badge rather than erroring
    return []
  }
}

export function useProjectPermissionTier(projectId: string): string | null {
  const { data } = useQuery({
    queryKey: ['ah-project-permissions'],
    queryFn: fetchPermissions,
    staleTime: POLL_SLOW,
    refetchInterval: POLL_SLOW * 2,
  })

  if (!data) return null
  const perm = data.find((p) => p.project_id === projectId)
  return perm?.permission_tier ?? null
}
