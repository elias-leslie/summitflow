import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ProjectHealthBadge } from './ProjectHealthBadge'

const fetchHealth = vi.hoisted(() => vi.fn())
vi.mock('@/lib/api', () => ({ fetchProjectHealth: fetchHealth }))

function renderBadge(
  endpoint = '/health',
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } }),
  baseUrl = 'https://summitflow.test',
) {
  return render(
    <QueryClientProvider client={client}>
      <ProjectHealthBadge
        project={{
          id: 'summitflow',
          name: 'SummitFlow',
          base_url: baseUrl,
          health_endpoint: endpoint,
          health_status: 'healthy',
        }}
      />
    </QueryClientProvider>,
  )
}

describe('ProjectHealthBadge', () => {
  beforeEach(() => {
    fetchHealth.mockReset().mockResolvedValue({
      project_id: 'summitflow',
      healthy: true,
      status_code: 200,
      response_time_ms: 0,
      checked_at: '2026-10-02T12:00:00Z',
    })
  })

  it('fetches lazily on keyboard focus and exposes live detail with zero latency', async () => {
    renderBadge()
    expect(fetchHealth).not.toHaveBeenCalled()
    fireEvent.focus(screen.getByRole('button'))
    const tooltip = await screen.findByRole('tooltip')
    expect(await screen.findByText('200')).toBeInTheDocument()
    expect(tooltip).toHaveTextContent('https://summitflow.test/health')
    expect(tooltip).toHaveTextContent('0 ms')
    expect(tooltip).toHaveTextContent('Checked')
    expect(screen.getByRole('button')).toHaveAttribute(
      'aria-describedby',
      tooltip.id,
    )
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument()
  })

  it('shows loading on hover and an unavailable request separately from unhealthy endpoints', async () => {
    fetchHealth.mockRejectedValue(new Error('Health API offline'))
    renderBadge()
    fireEvent.mouseEnter(screen.getByRole('button'))
    expect(screen.getByRole('status')).toHaveTextContent(
      'Checking health endpoint',
    )
    expect(
      await screen.findByText('Health check unavailable: Health API offline'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Needs attention')).not.toBeInTheDocument()
  })

  it('shows HTTP failures and their endpoint error', async () => {
    fetchHealth.mockResolvedValue({
      project_id: 'summitflow',
      healthy: false,
      status_code: 503,
      response_time_ms: 17,
      error: 'Service unavailable',
      checked_at: '2026-10-02T12:00:00Z',
    })
    renderBadge()
    fireEvent.mouseEnter(screen.getByRole('button'))
    expect(await screen.findByText('503')).toBeInTheDocument()
    expect(screen.getByRole('tooltip')).toHaveTextContent('Service unavailable')
    expect(screen.getByRole('button')).toHaveAccessibleName(
      'SummitFlow health: watch',
    )
  })

  it('does not check service-free projects or claim an endpoint succeeded', () => {
    renderBadge('')
    fireEvent.focus(screen.getByRole('button'))
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'No health endpoint configured.',
    )
    expect(fetchHealth).not.toHaveBeenCalled()
    expect(screen.queryByText('Healthy')).not.toBeInTheDocument()
  })

  it('does not probe a tool-only project with a default health path and no base URL', () => {
    renderBadge('/health', undefined, '')
    fireEvent.focus(screen.getByRole('button'))
    expect(screen.getByRole('tooltip')).toHaveTextContent(
      'No health endpoint configured.',
    )
    expect(fetchHealth).not.toHaveBeenCalled()
  })

  it('reuses health cached by another surface', async () => {
    const client = new QueryClient()
    client.setQueryData(['project-health', 'summitflow'], {
      project_id: 'summitflow',
      healthy: true,
      status_code: 204,
      response_time_ms: 5,
      checked_at: '2026-10-02T12:00:00Z',
    })
    renderBadge('/health', client)
    fireEvent.focus(screen.getByRole('button'))
    expect(await screen.findByText('204')).toBeInTheDocument()
    expect(fetchHealth).not.toHaveBeenCalled()
  })
})
