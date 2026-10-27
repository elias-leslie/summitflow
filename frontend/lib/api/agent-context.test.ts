import { afterEach, describe, expect, it, vi } from 'vitest'
import { buildAgentHubUiUrl, fetchProjectAgentContext } from './agent-context'

function respond(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

const valid = {
  project_id: 'summitflow',
  consumer_profile: 'agent_startup',
  consumer_surface: 'claude_code',
  status: 'ok',
  generated_at: '2026-10-27T20:00:00Z',
  items: [
    {
      order: 0,
      kind: 'project_index',
      group: 'project',
      source_id: 'project-index:summitflow',
      title: 'Project Index',
      authority: 'project_context',
      tier: 'project_index',
      required: false,
      disclosure: 'full',
      reason: "generated from the project's .index.yaml",
      char_count: 541,
      estimated_tokens: 135,
      edit_path: null,
      facts: ['project'],
    },
  ],
  withheld: { count: 0, estimated_tokens: 0 },
  totals: { items: 1, delivered_tokens: 135 },
  manage_path: '/runtime-context',
  failure: null,
}

describe('fetchProjectAgentContext', () => {
  afterEach(() => vi.restoreAllMocks())

  it('reads the summary through the Agent Hub proxy', async () => {
    const fetch = respond(valid)
    expect(await fetchProjectAgentContext('summitflow')).toEqual(valid)
    expect(fetch.mock.calls[0][0]).toBe(
      '/api/agent-hub/projects/summitflow/agent-context',
    )
  })

  it.each([
    null,
    { ...valid, project_id: 'agent-hub' },
    { ...valid, status: 'unknown' },
    { ...valid, items: [{ title: 'No ids' }] },
    { ...valid, totals: undefined },
  ])(
    'rejects invalid payloads instead of showing them as empty',
    async (body) => {
      respond(body)
      await expect(fetchProjectAgentContext('summitflow')).rejects.toThrow(
        'Invalid agent context response',
      )
    },
  )

  it('preserves proxy errors for the retry state', async () => {
    respond({ detail: 'Agent Hub error: offline' }, 502)
    await expect(fetchProjectAgentContext('summitflow')).rejects.toThrow(
      'Agent Hub error: offline',
    )
  })
})

describe('buildAgentHubUiUrl', () => {
  it('joins the base and an app path', () => {
    expect(
      buildAgentHubUiUrl('https://agent.example.test/', '/prompts/x'),
    ).toBe('https://agent.example.test/prompts/x')
  })

  it.each([
    [null, '/prompts/x'],
    ['https://agent.example.test', null],
    ['https://agent.example.test', 'https://elsewhere.test/x'],
  ])(
    'returns null without a base or a relative path (%s, %s)',
    (base, path) => {
      expect(buildAgentHubUiUrl(base, path)).toBeNull()
    },
  )
})
