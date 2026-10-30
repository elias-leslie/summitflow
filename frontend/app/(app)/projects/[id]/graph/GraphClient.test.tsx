import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GraphClient } from './GraphClient'

vi.mock('next/navigation', () => ({
  useParams: () => ({ id: 'summitflow' }),
}))

const STATUS = {
  project_id: 'summitflow',
  root_path: '/repo',
  graph_exists: true,
  html_available: false,
  report_available: false,
  node_count: 10,
  edge_count: 20,
  community_count: 2,
  graph_updated_at: null,
  html_updated_at: null,
  report_updated_at: null,
  html_url: null,
  report_url: null,
  code_node_count: 10,
  rationale_node_count: 0,
  semantic_node_count: 0,
  file_type_counts: {},
  detected_source_counts: {},
  semantic_source_count: 0,
  semantic_coverage: 'code_only',
  graph_stale: true,
  changed_files_since_graph: 3,
  changed_files_sample: [],
  graph_size_bytes: 0,
  html_size_bytes: 0,
  report_size_bytes: 0,
  html_uses_cdn: false,
  diagnostics: ['graph_stale', 'new_code'],
  unreadable_error: null,
}

function renderGraph(response: () => Response) {
  vi.spyOn(globalThis, 'fetch').mockImplementation(async () => response())
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <GraphClient />
    </QueryClientProvider>,
  )
}

describe('GraphClient', () => {
  afterEach(() => vi.restoreAllMocks())

  it('shows plain diagnostics and labels every command field', async () => {
    renderGraph(() => Response.json(STATUS))

    expect(
      await screen.findByText('Files changed since the last build'),
    ).toBeInTheDocument()
    expect(screen.getByText('new_code')).toBeInTheDocument()
    expect(screen.getByLabelText('Graph command')).toBeInTheDocument()
    expect(screen.getByLabelText('Question')).toBeInTheDocument()
    expect(screen.getByLabelText('Target node')).toBeInTheDocument()
    expect(screen.getByLabelText('Answer budget (tokens)')).toBeInTheDocument()
  })

  it('shows a failed status load instead of spinning', async () => {
    renderGraph(() => Response.json({ detail: 'boom' }, { status: 500 }))

    expect(
      await screen.findByText("Couldn't load the graph status"),
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Try again' })).toBeEnabled()
  })
})
