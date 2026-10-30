import { describe, expect, it, vi } from 'vitest'
import {
  buildAgentHubChatConfig,
  createAgentHubChatClient,
} from './agent-hub-chat-config'

describe('buildAgentHubChatConfig', () => {
  it('uses the provided project id for chat and memory scoping', () => {
    expect(buildAgentHubChatConfig({ projectId: 'agent-hub' })).toEqual({
      projectId: 'agent-hub',
      memoryGroupPrefix: 'agent-hub:',
    })
  })

  it('falls back to the default project when project id is missing', () => {
    expect(buildAgentHubChatConfig({})).toMatchObject({
      projectId: 'summitflow',
      memoryGroupPrefix: 'summitflow:',
    })
  })
})

describe('createAgentHubChatClient', () => {
  it('sends SDK requests to the Agent Hub proxy paths', async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify([]), {
        status: 200,
        headers: { 'Content-Type': 'application/json' },
      }),
    )
    const client = createAgentHubChatClient('/api/agent-hub', fetchMock)

    await client.sessions.get('s 1').catch(() => undefined)
    await client.turns.cancel('s1').catch(() => undefined)

    const urls = fetchMock.mock.calls.map((call) => String(call[0]))
    expect(urls[0]).toBe('/api/agent-hub/sessions/s%201?include_events=true')
    expect(urls[1]).toBe('/api/agent-hub/complete/cancel')
  })
})
