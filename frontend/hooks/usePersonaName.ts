import { POLL_SLOW } from '@/lib/polling'
import { useQuery } from '@tanstack/react-query'
import { getAgentHubProxyBase } from '@/lib/agent-hub-proxy'

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
    queryFn: async (): Promise<string> => {
      const base = getAgentHubProxyBase()
      const res = await fetch(`${base}/persona`)
      if (!res.ok) return fallback
      const data: PersonaResponse = await res.json()
      return data.name || fallback
    },
    staleTime: POLL_SLOW,
  })

  return data ?? fallback
}
