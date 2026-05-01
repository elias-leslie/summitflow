import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { ServiceGrid } from './ServiceGrid'

const queryMocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: queryMocks.useQuery,
}))

vi.mock('./ServiceCard', () => ({
  ServiceCard: () => <div data-testid="service-card" />,
}))

vi.mock('./ServiceListView', () => ({
  ServiceListView: () => <div data-testid="service-list" />,
}))

describe('ServiceGrid', () => {
  it('renders a runtime error state when the status query fails', () => {
    queryMocks.useQuery
      .mockReturnValueOnce({
        data: undefined,
        error: new Error('503: Runtime status unavailable'),
        isLoading: false,
      })
      .mockReturnValueOnce({
        data: undefined,
        error: undefined,
        isLoading: false,
      })
      .mockReturnValueOnce({
        data: undefined,
        error: undefined,
        isLoading: false,
      })

    render(<ServiceGrid />)

    expect(
      screen.getByText('Runtime status is unavailable.'),
    ).toBeInTheDocument()
    expect(
      screen.getByText('503: Runtime status unavailable'),
    ).toBeInTheDocument()
  })
})
