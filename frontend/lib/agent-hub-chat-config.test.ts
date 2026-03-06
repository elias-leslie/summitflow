import { describe, expect, it } from 'vitest'
import { buildAgentHubChatApiConfig } from './agent-hub-chat-config'

describe('buildAgentHubChatApiConfig', () => {
  it('uses the provided project id for chat and memory scoping', () => {
    expect(
      buildAgentHubChatApiConfig({
        proxyBase: '/api/agent-hub',
        projectId: 'agent-hub',
      }),
    ).toEqual({
      completeEndpoint: '/api/agent-hub/complete',
      sessionsEndpoint: '/api/agent-hub/sessions',
      preferencesEndpoint: '/api/agent-hub/preferences',
      projectId: 'agent-hub',
      memoryGroupPrefix: 'agent-hub:',
    })
  })

  it('falls back to the default project when project id is missing', () => {
    expect(
      buildAgentHubChatApiConfig({
        proxyBase: '/api/agent-hub',
      }),
    ).toMatchObject({
      projectId: 'summitflow',
      memoryGroupPrefix: 'summitflow:',
    })
  })
})
