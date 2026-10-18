import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { CleanupSettings } from './CleanupSettings'

const mocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
  mutate: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => ({
  useQuery: mocks.useQuery,
  useMutation: () => ({ mutate: mocks.mutate, isPending: false, error: null }),
  useQueryClient: () => ({ setQueryData: vi.fn() }),
}))

const setting = {
  name: 'agent_tmp_max_age_hours',
  value: 72,
  default: 72,
  saved: false,
  min: 6,
  max: 720,
}

describe('CleanupSettings', () => {
  it('saves a changed value and refuses one out of range', () => {
    mocks.useQuery.mockReturnValue({
      data: { settings: [setting] },
      error: null,
      isLoading: false,
    })
    render(<CleanupSettings />)
    const input = screen.getByLabelText(/Agent temp folders/)
    const save = screen.getByRole('button', { name: 'Save' })
    expect(save).toBeDisabled()
    fireEvent.change(input, { target: { value: '2' } })
    expect(save).toBeDisabled()
    fireEvent.change(input, { target: { value: '48' } })
    fireEvent.click(save)
    expect(mocks.mutate).toHaveBeenCalledWith({
      name: 'agent_tmp_max_age_hours',
      value: 48,
    })
  })

  it('offers a reset when a value was saved', () => {
    mocks.useQuery.mockReturnValue({
      data: { settings: [{ ...setting, value: 24, saved: true }] },
      error: null,
      isLoading: false,
    })
    render(<CleanupSettings />)
    fireEvent.click(screen.getByRole('button', { name: 'Reset to 72' }))
    expect(mocks.mutate).toHaveBeenCalledWith({
      name: 'agent_tmp_max_age_hours',
      value: null,
    })
  })
})
