import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type {
  AgentContextItem,
  ProjectAgentContext as Context,
} from '@/lib/api'
import { ProjectAgentContext } from './ProjectAgentContext'

const apiMocks = vi.hoisted(() => ({
  fetchProjectAgentContext: vi.fn(),
  fetchProject: vi.fn(),
}))

vi.mock('@/lib/api', async () => {
  const actual = await vi.importActual<
    typeof import('@/lib/api/agent-context')
  >('@/lib/api/agent-context')
  return {
    buildAgentHubUiUrl: actual.buildAgentHubUiUrl,
    fetchProjectAgentContext: apiMocks.fetchProjectAgentContext,
    fetchProject: apiMocks.fetchProject,
  }
})

function item(overrides: Partial<AgentContextItem>): AgentContextItem {
  return {
    order: 0,
    kind: 'prompt',
    group: 'global',
    source_id: 'safety-directive',
    title: 'Safety Directive',
    authority: 'operator_guardrail',
    tier: 'global_guardrail',
    required: true,
    disclosure: 'full',
    reason: 'global scope; always',
    char_count: 2198,
    estimated_tokens: 549,
    edit_path: '/prompts/safety-directive',
    facts: [],
    ...overrides,
  }
}

function context(overrides: Partial<Context> = {}): Context {
  const items = [
    item({}),
    item({
      order: 1,
      kind: 'memory',
      group: 'project',
      source_id: 'mem-1',
      title: 'Choose the right security tool',
      tier: 'guardrail',
      reason: 'guardrail tier',
      estimated_tokens: 173,
      edit_path: '/memory?scope=project',
    }),
    item({
      order: 2,
      group: 'project',
      source_id: 'security-research-operating-policy',
      title: 'Security Research Operating Policy',
      required: false,
      reason: 'project scope; always',
      estimated_tokens: 1361,
      edit_path: '/prompts/security-research-operating-policy',
    }),
    item({
      order: 3,
      kind: 'project_index',
      group: 'project',
      source_id: 'project-index:security-research',
      title: 'Project Index',
      required: false,
      reason: "generated from the project's .index.yaml",
      estimated_tokens: 61,
      edit_path: null,
      facts: ['project', 'urls'],
    }),
  ]
  return {
    project_id: 'security-research',
    consumer_profile: 'agent_startup',
    consumer_surface: 'claude_code',
    status: 'ok',
    generated_at: '2026-10-27T20:00:00Z',
    items,
    withheld: { count: 0, estimated_tokens: 0 },
    totals: {
      items: 4,
      project_items: 3,
      global_items: 1,
      project_tokens: 1595,
      global_tokens: 549,
      item_tokens: 2144,
      delivered_tokens: 2150,
      delivered_chars: 8600,
    },
    manage_path: '/runtime-context',
    failure: null,
    ...overrides,
  }
}

function renderPanel() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <ProjectAgentContext projectId="security-research" />
    </QueryClientProvider>,
  )
}

describe('ProjectAgentContext', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    apiMocks.fetchProject.mockResolvedValue({
      id: 'agent-hub',
      base_url: 'http://127.0.0.1:3003',
      public_url: 'https://agent.example.test/',
    })
    apiMocks.fetchProjectAgentContext.mockResolvedValue(context())
  })

  it('lists project items first with tokens and Agent Hub edit links', async () => {
    renderPanel()

    const project = await screen.findByRole('region', {
      name: /Project-specific/,
    })
    const rows = within(project).getAllByRole('listitem')
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining('Choose the right security tool'),
      expect.stringContaining('Security Research Operating Policy'),
      expect.stringContaining('Project Index'),
    ])
    expect(
      within(project).getByRole('link', {
        name: 'Edit Security Research Operating Policy in Agent Hub',
      }),
    ).toHaveAttribute(
      'href',
      'https://agent.example.test/prompts/security-research-operating-policy',
    )
    expect(
      within(project).getByRole('link', {
        name: 'Edit Choose the right security tool in Agent Hub',
      }),
    ).toHaveAttribute('href', 'https://agent.example.test/memory?scope=project')
    expect(within(project).getByText('~1,361 tokens')).toBeInTheDocument()
    expect(
      within(project).getByText('Generated from .index.yaml'),
    ).toBeInTheDocument()
    expect(within(project).getByText(/project, urls/)).toBeInTheDocument()
    expect(screen.getByText(/new Claude Code session/)).toBeInTheDocument()
    expect(
      screen.getByRole('link', { name: 'Runtime context in Agent Hub' }),
    ).toHaveAttribute('href', 'https://agent.example.test/runtime-context')
  })

  it('keeps global items in a collapsed summary', async () => {
    renderPanel()

    const summary = await screen.findByText('Global context')
    const details = summary.closest('details')
    expect(details).not.toHaveAttribute('open')
    expect(
      within(details as HTMLElement).getByText(/1 item · ~549 tokens/),
    ).toBeInTheDocument()
    fireEvent.click(summary)
    expect(details).toHaveAttribute('open')
    expect(
      within(details as HTMLElement).getByText('Safety Directive'),
    ).toBeInTheDocument()
  })

  it('says when nothing project-specific is delivered and counts withheld memories', async () => {
    const base = context()
    apiMocks.fetchProjectAgentContext.mockResolvedValue(
      context({
        items: base.items.filter((entry) => entry.group === 'global'),
        withheld: { count: 2, estimated_tokens: 300 },
        totals: {
          ...base.totals,
          items: 1,
          project_items: 0,
          project_tokens: 0,
        },
      }),
    )
    renderPanel()

    expect(
      await screen.findByText(
        'Nothing project-specific is delivered at startup.',
      ),
    ).toBeInTheDocument()
    expect(
      screen.getByText('2 sensitive memories not listed (~300 tokens).'),
    ).toBeInTheDocument()
  })

  it('shows titles without links when the Agent Hub address is unknown', async () => {
    apiMocks.fetchProject.mockRejectedValue(new Error('not registered'))
    renderPanel()

    await screen.findByText('Security Research Operating Policy')
    expect(screen.queryByRole('link')).not.toBeInTheDocument()
    expect(screen.getAllByText('Agent Hub link unavailable')).toHaveLength(3)
  })

  it('shows the load error with a retry', async () => {
    apiMocks.fetchProjectAgentContext.mockRejectedValueOnce(
      new Error('Agent Hub error: offline'),
    )
    renderPanel()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Agent Hub error: offline',
    )
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    expect(
      await screen.findByText('Security Research Operating Policy'),
    ).toBeInTheDocument()
  })

  it('reports a failed delivery instead of an empty list', async () => {
    apiMocks.fetchProjectAgentContext.mockResolvedValue(
      context({
        status: 'failed',
        items: [],
        failure: { error_type: 'RuntimeError', message: 'memory store down' },
      }),
    )
    renderPanel()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      "Agent Hub could not assemble this project's startup context: memory store down",
    )
    expect(screen.queryByText('Global context')).not.toBeInTheDocument()
  })
})
