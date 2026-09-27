import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HostMonitorDiagnostics } from './HostMonitorDiagnostics'

const mocks = vi.hoisted(() => ({ useQuery: vi.fn(), useMutation: vi.fn() }))
vi.mock('@tanstack/react-query', () => mocks)

const envelope = (items: unknown[], coverage = { availability: 'ok' }) => ({
  schema: 1,
  generated_at: '2026-09-27T12:00:00Z',
  requested: {},
  coverage,
  items,
  next_cursor: null,
  truncated: false,
  errors: [],
})

describe('HostMonitorDiagnostics system views', () => {
  it('queries all system journal entries and technical socket details', () => {
    const queries: Array<{ queryKey: unknown[]; queryFn: () => unknown }> = []
    mocks.useQuery.mockImplementation((options) => {
      queries.push(options)
      const section = options.queryKey[1]
      return {
        data:
          section === 'log-services'
            ? envelope([{ value: { service: 'ssh.service', scope: 'system' } }])
            : section === 'diagnostic' && options.queryKey[2] === 'logs'
              ? { ...envelope([]), next_cursor: 'journal-next' }
              : section === 'diagnostic' &&
                  options.queryKey[2] === 'connections'
                ? {
                    ...envelope([
                      {
                        value: {
                          protocol: 'tcp',
                          state: 'ESTABLISHED',
                          local: '127.0.0.1:22',
                          remote: '127.0.0.1:1234',
                          pid: 42,
                        },
                      },
                    ]),
                    next_cursor: 'socket-next',
                  }
                : envelope([]),
        isLoading: false,
        error: null,
      }
    })
    mocks.useMutation.mockReturnValue({
      mutate: vi.fn(),
      isPending: false,
      error: null,
    })
    render(
      <HostMonitorDiagnostics
        serviceNames={['summitflow.service']}
        selectedService={null}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: 'Logs' }))
    fireEvent.change(screen.getByRole('combobox', { name: /Log source/ }), {
      target: { value: 'system' },
    })
    const logs = queries.at(-1)
    expect(logs?.queryKey).toContain('system')
    expect(logs?.queryFn).toBeTypeOf('function')
    expect(
      screen.getByRole('option', { name: 'ssh.service' }),
    ).toBeInTheDocument()
    expect(
      screen.getByRole('option', { name: 'All services' }),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(queries.at(-1)?.queryKey).toContain('journal-next')
    fireEvent.click(screen.getByRole('button', { name: 'Previous page' }))

    fireEvent.click(screen.getByRole('button', { name: 'Connections' }))
    expect(screen.getAllByText(/127.0.0.1:22/).length).toBeGreaterThan(0)
    fireEvent.click(screen.getByRole('button', { name: 'Next page' }))
    expect(queries.at(-1)?.queryKey).toContain('socket-next')
    expect(
      screen.queryByRole('checkbox', { name: /addresses|PIDs/i }),
    ).not.toBeInTheDocument()
  })

  it('selects an available container without unsupported filters', () => {
    const queries: Array<{ queryKey: unknown[] }> = []
    mocks.useQuery.mockImplementation((options) => {
      queries.push(options)
      return {
        data:
          options.queryKey[1] === 'log-services'
            ? envelope([
                {
                  value: {
                    service: 'web',
                    container_id: 'abc123',
                    scope: 'container',
                  },
                },
              ])
            : envelope([]),
        isLoading: false,
        error: null,
      }
    })
    render(<HostMonitorDiagnostics serviceNames={[]} selectedService={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'Logs' }))
    fireEvent.change(screen.getByRole('combobox', { name: /Log source/ }), {
      target: { value: 'container' },
    })
    expect(screen.getByRole('combobox', { name: /Container/ })).toHaveValue(
      'web',
    )
    expect(
      screen.queryByRole('option', { name: 'All services' }),
    ).not.toBeInTheDocument()
    expect(
      screen.queryByRole('combobox', { name: /Priority/ }),
    ).not.toBeInTheDocument()
    expect(queries.at(-1)?.queryKey).toContain('web')
  })

  it('shows mounted capacity and scans a selected mount', () => {
    const mutate = vi.fn()
    mocks.useMutation.mockReturnValue({ mutate, isPending: false, error: null })
    mocks.useQuery.mockImplementation(
      ({ queryKey }: { queryKey: unknown[] }) => ({
        data:
          queryKey[1] === 'mounts'
            ? {
                ...envelope([
                  {
                    value: {
                      mountpoint: '/data',
                      source: '/dev/sdb1',
                      filesystem: 'ext4',
                      total_bytes: 1073741824,
                      available_bytes: 536870912,
                    },
                  },
                ]),
                next_cursor: queryKey[2] ? null : 'mount-next',
              }
            : envelope([]),
        isLoading: false,
        error: null,
        refetch: vi.fn(),
      }),
    )
    render(<HostMonitorDiagnostics serviceNames={[]} selectedService={null} />)
    fireEvent.click(screen.getByRole('button', { name: 'Disk space' }))
    expect(screen.getByText('/data')).toBeInTheDocument()
    expect(screen.getByText('1.0 GiB')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText(/Page 2/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Previous' }))
    fireEvent.click(screen.getByRole('button', { name: 'Scan' }))
    expect(mutate).toHaveBeenCalledWith('/data')
  })
})
