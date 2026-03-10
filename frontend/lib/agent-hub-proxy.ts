/**
 * Resolve the Agent Hub API base path.
 *
 * Browser requests must stay same-origin so Next.js can rewrite
 * /api/agent-hub/* through the local proxy route.
 */
export function getAgentHubProxyBase(): string {
  if (typeof window === 'undefined') {
    return 'http://localhost:8001/api/agent-hub'
  }

  return '/api/agent-hub'
}
