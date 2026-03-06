import type { ChatStreamApiConfig } from '@agent-hub/chat-ui'
import { getProjectIdOrDefault, getProjectMemoryGroupPrefix } from './project-config'

interface BuildAgentHubChatApiConfigOptions {
  proxyBase: string
  projectId?: string | null
}

export function buildAgentHubChatApiConfig({
  proxyBase,
  projectId,
}: BuildAgentHubChatApiConfigOptions): ChatStreamApiConfig {
  const effectiveProjectId = getProjectIdOrDefault(projectId)

  return {
    completeEndpoint: `${proxyBase}/complete`,
    sessionsEndpoint: `${proxyBase}/sessions`,
    preferencesEndpoint: `${proxyBase}/preferences`,
    projectId: effectiveProjectId,
    memoryGroupPrefix: getProjectMemoryGroupPrefix(effectiveProjectId),
  }
}
