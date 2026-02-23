import { useQuery } from '@tanstack/react-query'

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
  const res = await fetch('/api/agent-hub/projects/permissions')
  if (!res.ok) return []
  return res.json()
}

export function useProjectPermissionTier(projectId: string): string | null {
  const { data } = useQuery({
    queryKey: ['ah-project-permissions'],
    queryFn: fetchPermissions,
    staleTime: 60_000,
    refetchInterval: 120_000,
  })

  if (!data) return null
  const perm = data.find((p) => p.project_id === projectId)
  return perm?.permission_tier ?? null
}
