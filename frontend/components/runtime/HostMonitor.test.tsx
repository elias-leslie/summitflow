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

const process = (
  pid: number,
  ppid: number,
  name: string,
  tree: Record<string, unknown>,
) => ({
  identity: { boot_id: 'boot-a', pid, start_ticks: pid * 10 },
  process: { pid, ppid, name, state: 'running' },
  sampled_at: '2026-09-26T12:00:00Z',
  observed_at: '2026-09-26T12:00:00Z',
  mode: 'detail',
  sort_availability: 'ok',
  sort_value: 1,
  tree,
})

describe('HostMonitor process tree', () => {
  it('uses snapshot ancestry across pages and supports local collapse and list switching', () => {
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
                process(10, 1, 'parent', {
                  depth: 0,
                  children: 1,
                  parent_link: 'unavailable_in_capture',
                }),
                process(21, 10, 'child', {
                  depth: 1,
                  children: 0,
                  parent_link: 'linked',
                  parent_identity: {
                    boot_id: 'boot-a',
                    pid: 10,
                    start_ticks: 100,
                  },
                }),
                process(30, 999, 'orphan', {
                  depth: 0,
                  children: 0,
                  parent_link: 'unavailable_in_capture',
                }),
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
        name: /orphan, PID 30, level 1, parent unavailable in this capture/,
      }),
    ).toBeInTheDocument()
    expect(
      screen.getByText(
        /Tree order and ancestry come from one captured observation/,
      ),
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

    fireEvent.click(screen.getByRole('button', { name: 'List' }))
    expect(
      screen.queryByText(
        /Tree order and ancestry come from one captured observation/,
      ),
    ).not.toBeInTheDocument()
    fireEvent.change(
      screen.getByRole('searchbox', { name: /Filter this page/ }),
      {
        target: { value: 'child' },
      },
    )
    expect(screen.getByRole('button', { name: 'child' })).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: 'parent' }),
    ).not.toBeInTheDocument()
  })

  it('pins the first page when returning after a newer sample arrives', () => {
    queryMocks.useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    queryMocks.useMutation.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isSuccess: false,
      error: null,
    })
    let newerSample = false
    const older = {
      ...envelope([
        process(10, 0, 'old root', {
          depth: 0,
          children: 1,
          parent_link: 'root',
        }),
      ]),
      coverage: { observation_cursor: 'pinned-first' },
      next_cursor: 'second-page',
    }
    const second = envelope([
      process(21, 10, 'old child', {
        depth: 1,
        children: 0,
        parent_link: 'linked',
        parent_identity: { boot_id: 'boot-a', pid: 10, start_ticks: 100 },
      }),
    ])
    queryMocks.useQuery.mockImplementation(
      ({ queryKey }: { queryKey: unknown[] }) => ({
        data:
          queryKey[1] === 'processes'
            ? queryKey.at(-1) === 'second-page'
              ? second
              : queryKey.at(-1) === 'pinned-first' || !newerSample
                ? older
                : envelope([
                    process(99, 0, 'new root', {
                      depth: 0,
                      children: 0,
                      parent_link: 'root',
                    }),
                  ])
            : envelope([]),
        isLoading: false,
        error: null,
      }),
    )
    render(<HostMonitor />)
    fireEvent.click(screen.getByRole('button', { name: 'Tree' }))
    expect(
      screen.queryByRole('combobox', { name: 'Sort' }),
    ).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next processes' }))
    expect(
      screen.getByRole('button', { name: /old child, PID 21/ }),
    ).toBeInTheDocument()
    newerSample = true
    fireEvent.click(screen.getByRole('button', { name: 'Previous processes' }))
    expect(
      screen.getByRole('button', { name: /old root, PID 10/ }),
    ).toBeInTheDocument()
    expect(
      screen.queryByRole('button', { name: /new root, PID 99/ }),
    ).not.toBeInTheDocument()
  })
})

describe('HostMonitor GPU history', () => {
  it('shows sparse poll provenance, device nulls, and boot-scoped drilldown', () => {
    queryMocks.useQueryClient.mockReturnValue({ invalidateQueries: vi.fn() })
    queryMocks.useMutation.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      isSuccess: false,
      error: null,
    })
    const keys: unknown[][] = []
    const gpu = {
      ...envelope([
        {
          identity: { boot_id: 'boot-a', index: 0 },
          device: {
            name: 'GPU A',
            utilization_pct: 42,
            memory_used_bytes: 1024,
            memory_total_bytes: 4096,
            temperature_c: null,
            power_w: 75,
          },
        },
      ]),
      coverage: {
        provider: 'nvidia-smi',
        availability: 'partial',
        freshness: 'stale',
        observed_at: '2026-09-26T12:00:00Z',
        age_seconds: 40,
        poll_interval_seconds: 15,
        boot_id: 'boot-a',
        devices_seen: 1,
        devices_scanned: 1,
        max_utilization_pct: 42,
        memory_used_bytes: 1024,
        memory_total_bytes: 4096,
        source_errors: ['field_unavailable'],
      },
    }
    const history = envelope([
      {
        sampled_at: '2026-09-26T11:59:45Z',
        observed_at: '2026-09-26T11:59:47Z',
        value: { last: 42 },
        availability: 'ok',
        provider: 'nvidia-smi',
        coverage: { observed: 1, missing: 0 },
      },
      {
        sampled_at: '2026-09-26T12:00:00Z',
        value: null,
        availability: 'not_collected',
        coverage: { observed: 0, missing: 1 },
      },
    ])
    queryMocks.useQuery.mockImplementation(
      ({ queryKey }: { queryKey: unknown[] }) => {
        keys.push(queryKey)
        return {
          data:
            queryKey[1] === 'gpu'
              ? gpu
              : queryKey[1] === 'gpu-series'
                ? history
                : envelope([]),
          isLoading: false,
          error: null,
        }
      },
    )
    render(<HostMonitor />)
    expect(screen.getByText(/stale · partial/)).toBeInTheDocument()
    expect(
      screen.getByText(/Source errors: field_unavailable/),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('img', {
        name: /gpu_max_utilization_pct history; gaps are not connected/,
      }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /GPU A · index 0/ }))
    expect(screen.getByText(/temperature Unavailable/)).toBeInTheDocument()
    expect(
      keys.some(
        (key) =>
          key[1] === 'gpu-series' && key[2] === 'gpu:0' && key[3] === 'boot-a',
      ),
    ).toBe(true)
    fireEvent.change(screen.getByRole('combobox', { name: /GPU metric/ }), {
      target: { value: 'gpu_temperature_c' },
    })
    expect(
      keys.some(
        (key) => key[1] === 'gpu-series' && key[4] === 'gpu_temperature_c',
      ),
    ).toBe(true)
  })
})
