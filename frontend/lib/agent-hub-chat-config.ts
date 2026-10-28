import type { ChatStreamConfig } from '@agent-hub/chat-ui'
import { createClient } from '@agent-hub/sdk'
import {
  getProjectIdOrDefault,
  getProjectMemoryGroupPrefix,
} from './project-config'

interface BuildAgentHubChatConfigOptions {
  projectId?: string | null
}

export function buildAgentHubChatConfig({
  projectId,
}: BuildAgentHubChatConfigOptions = {}): ChatStreamConfig {
  const effectiveProjectId = getProjectIdOrDefault(projectId)

  return {
    projectId: effectiveProjectId,
    memoryGroupPrefix: getProjectMemoryGroupPrefix(effectiveProjectId),
  }
}

/**
 * An Agent Hub client that goes through SummitFlow's proxy. The proxy maps
 * `<proxyBase>/<path>` to Agent Hub's `/api/<path>`, while the SDK asks for
 * `/api/<path>`, so the leading `/api` of each request is dropped.
 */
export function createAgentHubChatClient(
  proxyBase: string,
  fetchImpl: typeof fetch = (...args) => globalThis.fetch(...args),
) {
  const prefix = `${proxyBase.replace(/\/+$/, '')}/api/`
  const proxied: typeof fetch = (input, init) =>
    typeof input === 'string' && input.startsWith(prefix)
      ? fetchImpl(
          `${proxyBase.replace(/\/+$/, '')}/${input.slice(prefix.length)}`,
          init,
        )
      : fetchImpl(input, init)
  return createClient({ baseUrl: proxyBase, fetch: proxied })
}
