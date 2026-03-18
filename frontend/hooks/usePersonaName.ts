import { useQuery } from '@tanstack/react-query'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'
import { fetchWithErrorHandling } from '@/lib/api'
import { POLL_SLOW } from '@/lib/polling'

interface PersonaResponse {
  name: string
}

/**
 * Fetch the persona display name from Agent Hub.
 * Returns the configured name (e.g. "Jenny") or a fallback.
 */
export function usePersonaName(fallback = 'Persona'): string {
  const { data } = useQuery({
    queryKey: ['persona-name'],
    queryFn: () =>
      fetchWithErrorHandling<PersonaResponse>(`${getAgentHubProxyBase()}/persona`, {
        errorMessage: 'Failed to fetch persona name',
      }).then((res) => res.name || fallback),
    staleTime: POLL_SLOW,
  })

  return data ?? fallback
}
