/**
 * Agent Hub proxy Route Handler.
 *
 * Lives at /proxy-hub/agent-hub/[...path] and is reached via a beforeFiles
 * rewrite: /api/agent-hub/* -> /proxy-hub/agent-hub/* (see next.config.ts).
 * This ensures agent-hub requests are intercepted before the catch-all
 * /api/* -> localhost:8001 rewrite can grab them.
 *
 * Uses @agent-hub/proxy for shared auth injection and SSE streaming.
 */
import { createRouteHandlers } from '@agent-hub/proxy/next'

export const { GET, POST, PUT, DELETE } = createRouteHandlers({
  envPrefix: 'SUMMITFLOW',
})
