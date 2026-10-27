import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { GenerateMockupDialog } from './GenerateMockupDialog'

function mockPages(body: unknown, status = 200) {
  return vi.spyOn(globalThis, 'fetch').mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  )
}

function renderDialog() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <GenerateMockupDialog
        projectId="summitflow"
        open
        onOpenChange={() => {}}
      />
    </QueryClientProvider>,
  )
}

async function openDropdown() {
  const trigger = await screen.findByRole('button', {
    name: /choose a page to analyze/i,
  })
  fireEvent.click(trigger)
}

describe('GenerateMockupDialog page picker', () => {
  afterEach(() => vi.restoreAllMocks())

  it('lists discovered pages and fills in the resolved page URL', async () => {
    const fetch = mockPages({
      items: [
        { path: '/settings', name: 'Settings', url: null, port: 3001 },
        {
          path: '/docs',
          name: 'Docs',
          url: 'https://docs.example.test/docs',
          port: null,
        },
      ],
    })
    renderDialog()

    await openDropdown()
    expect(fetch.mock.calls[0][0]).toBe('/api/projects/summitflow/pages')

    fireEvent.click(screen.getByRole('button', { name: /settings/i }))
    expect(
      screen.getByText('http://localhost:3001/settings'),
    ).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: /settings/i }))
    fireEvent.click(screen.getByRole('button', { name: /docs/i }))
    expect(
      screen.getByText('https://docs.example.test/docs'),
    ).toBeInTheDocument()
  })

  it('says no pages were discovered when the list is empty', async () => {
    mockPages({ items: [] })
    renderDialog()

    await openDropdown()
    expect(
      screen.getByText('No pages were discovered for this project'),
    ).toBeInTheDocument()
    expect(screen.queryByText(/scan/i)).not.toBeInTheDocument()
  })

  it('reports a failed page lookup instead of an empty list', async () => {
    mockPages({ message: 'boom' }, 503)
    renderDialog()

    await openDropdown()
    expect(
      await screen.findByText('Failed to load project pages'),
    ).toBeInTheDocument()
  })
})
