import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { type AuthMe, fetchAuthMe } from '@/lib/api/auth'
import { AppAuthGate } from './AppAuthGate'

const { replace } = vi.hoisted(() => ({ replace: vi.fn() }))
vi.mock('next/navigation', () => ({
  usePathname: () => '/',
  useRouter: () => ({ replace }),
}))
vi.mock('@/lib/api/auth', () => ({ fetchAuthMe: vi.fn() }))

const owner: AuthMe = {
  authenticated: true,
  email: 'owner@example.test',
  role: 'owner',
  is_owner: true,
  is_viewer: false,
  is_local_bypass: false,
  grants: [],
}

function renderGate() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  render(
    <QueryClientProvider client={client}>
      <AppAuthGate>Protected content</AppAuthGate>
    </QueryClientProvider>,
  )
  return client
}

describe('AppAuthGate', () => {
  beforeEach(() => vi.resetAllMocks())

  it('shows a service error instead of an owner denial and recovers on retry', async () => {
    vi.mocked(fetchAuthMe).mockRejectedValueOnce(
      new Error('Service unavailable'),
    )
    vi.mocked(fetchAuthMe).mockResolvedValueOnce(owner)
    renderGate()

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'Unable to check SummitFlow access',
    )
    expect(
      screen.queryByText(/Your authenticated email is not an owner/),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(await screen.findByText('Protected content')).toBeInTheDocument()
    expect(fetchAuthMe).toHaveBeenCalledTimes(2)
  })

  it('retains the access denial for a successful non-owner response', async () => {
    vi.mocked(fetchAuthMe).mockResolvedValue({
      ...owner,
      role: 'none',
      is_owner: false,
    })
    renderGate()
    expect(
      await screen.findByText('SummitFlow access is not enabled'),
    ).toBeInTheDocument()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'Try again' }),
    ).not.toBeInTheDocument()
  })

  it('redirects viewers without showing an owner denial', async () => {
    vi.mocked(fetchAuthMe).mockResolvedValue({
      ...owner,
      role: 'viewer',
      is_owner: false,
      is_viewer: true,
    })
    renderGate()
    await waitFor(() => expect(replace).toHaveBeenCalledWith('/viewer'))
    expect(
      screen.queryByText('SummitFlow access is not enabled'),
    ).not.toBeInTheDocument()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
  })

  it('does not expose cached owner content when access revalidation fails', async () => {
    vi.mocked(fetchAuthMe).mockResolvedValueOnce(owner)
    const client = renderGate()
    expect(await screen.findByText('Protected content')).toBeInTheDocument()
    vi.mocked(fetchAuthMe).mockRejectedValueOnce(new Error('Network failure'))
    await client.invalidateQueries({ queryKey: ['auth-me'] })
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.queryByText('Protected content')).not.toBeInTheDocument()
  })
})
