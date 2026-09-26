import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HostMonitor } from './HostMonitor'

const queryMocks = vi.hoisted(() => ({
  useQuery: vi.fn(),
  useMutation: vi.fn(),
  useQueryClient: vi.fn(),
}))

vi.mock('@tanstack/react-query', () => queryMocks)
vi.mock('./HostMonitorDiagnostics', () => ({
  HostMonitorDiagnostics: () => null,
}))

const envelope = (items: unknown[]) => ({
  schema: 1,
  generated_at: '2026-09-26T12:00:00Z',
  requested: {},
  coverage: {},
  items,
  next_cursor: null,
  truncated: false,
  errors: [],
})

const process = (pid: number, ppid: number, name: string) => ({
  identity: { boot_id: 'boot-a', pid, start_ticks: pid * 10 },
  process: { pid, ppid, name, state: 'running' },
  sampled_at: '2026-09-26T12:00:00Z',
  observed_at: '2026-09-26T12:00:00Z',
  mode: 'detail',
  sort_availability: 'ok',
  sort_value: 1,
})

describe('HostMonitor process tree', () => {
  it('groups only returned parents and supports collapse and list switching', () => {
    queryMocks.useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    queryMocks.useMutation.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isSuccess: false,
      error: null,
    })
    queryMocks.useQuery.mockImplementation(
      ({ queryKey }: { queryKey: string[] }) => ({
        data:
          queryKey[1] === 'processes'
            ? envelope([
                process(21, 10, 'child'),
                process(10, 1, 'parent'),
                process(30, 999, 'orphan'),
              ])
            : envelope([]),
        isLoading: false,
        error: null,
      }),
    )

    render(<HostMonitor />)
    expect(
      screen.queryByRole('button', { name: /Collapse parent/ }),
    ).not.toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Tree' }))
    const rows = within(screen.getByRole('table')).getAllByRole('row')
    expect(rows[1]).toHaveTextContent('parent')
    expect(rows[2]).toHaveTextContent('child')
    expect(rows[3]).toHaveTextContent('orphan')
    expect(
      screen.getByRole('button', {
        name: /orphan, PID 30, level 1, parent not linked among displayed rows/,
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(/Parent links use this page’s returned rows/),
    ).toBeInTheDocument()

    const collapse = screen.getByRole('button', {
      name: 'Collapse parent PID 10',
    })
    expect(collapse).toHaveAttribute('aria-expanded', 'true')
    fireEvent.click(collapse)
    expect(
      screen.queryByRole('button', { name: /^child, PID 21/ }),
    ).not.toBeInTheDocument()
    expect(screen.getByText(/2 shown; expand branches/)).toBeInTheDocument()
    fireEvent.click(
      screen.getByRole('button', { name: 'Expand parent PID 10' }),
    )
    expect(
      screen.getByRole('button', { name: /^child, PID 21/ }),
    ).toBeInTheDocument()

    fireEvent.change(
      screen.getByRole('searchbox', { name: /Filter this page/ }),
      {
        target: { value: 'child' },
      },
    )
    expect(
      screen.getByRole('button', { name: /^child, PID 21/ }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'parent' }),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'List' }))
    expect(
      screen.queryByText(/Parent links use this page’s returned rows/),
    ).not.toBeInTheDocument()
  })
})
