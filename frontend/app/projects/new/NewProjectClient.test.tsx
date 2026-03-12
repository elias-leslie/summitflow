import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { NewProjectClient } from './NewProjectClient'

const routerMocks = vi.hoisted(() => ({
  push: vi.fn(),
  useRouter: vi.fn(),
}))

const apiMocks = vi.hoisted(() => ({
  createProject: vi.fn(),
}))

vi.mock('next/navigation', () => ({
  useRouter: routerMocks.useRouter,
}))

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string
    children: React.ReactNode
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/api', () => ({
  createProject: apiMocks.createProject,
}))

function renderClient() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
      mutations: { retry: false },
    },
  })

  return render(
    <QueryClientProvider client={queryClient}>
      <NewProjectClient />
    </QueryClientProvider>,
  )
}

describe('NewProjectClient', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    routerMocks.useRouter.mockReturnValue({ push: routerMocks.push })
    apiMocks.createProject.mockResolvedValue({
      id: 'my-project',
      name: 'My Project',
    })
  })

  it('normalizes project registration fields before submitting', async () => {
    renderClient()

    fireEvent.change(screen.getByLabelText('Project Name *'), {
      target: { value: 'My Project!!' },
    })
    fireEvent.change(screen.getByLabelText('Base URL *'), {
      target: { value: 'https://example.com///' },
    })
    fireEvent.change(screen.getByLabelText('Health Endpoint'), {
      target: { value: 'healthz' },
    })

    expect(screen.getByText('Normalized to')).toBeInTheDocument()
    expect(screen.getByText('https://example.com/healthz')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Create Project' }))

    await waitFor(() => {
      expect(apiMocks.createProject).toHaveBeenCalled()
    })
    expect(apiMocks.createProject.mock.calls[0]?.[0]).toEqual({
      id: 'my-project',
      name: 'My Project!!',
      base_url: 'https://example.com',
      health_endpoint: '/healthz',
    })
  })
})
