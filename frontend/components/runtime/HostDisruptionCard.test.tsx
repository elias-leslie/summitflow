import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { HostDisruptionCard } from './HostDisruptionCard'

const queryMocks = vi.hoisted(() => ({ useQuery: vi.fn() }))

vi.mock('@tanstack/react-query', () => ({ useQuery: queryMocks.useQuery }))

function snapshot(extra: Record<string, unknown> = {}) {
  return {
    target: 'host',
    host: 'davion-sidarli',
    generated_at: new Date().toISOString(),
    clear: true,
    blocking: [],
    unknown: [],
    agents: [],
    handshakes: [],
    holds: [],
    leases: [],
    backups: { summitflow: [], units: [], processes: [] },
    ...extra,
  }
}

function mock(data: ReturnType<typeof snapshot>) {
  queryMocks.useQuery.mockReturnValue({
    data,
    error: undefined,
    isLoading: false,
  })
}

describe('HostDisruptionCard', () => {
  it('says nothing is in the way and keeps the zero agent count', () => {
    mock(snapshot())
    render(<HostDisruptionCard />)
    expect(
      screen.getByText('Nothing in the way · no agents working'),
    ).toBeInTheDocument()
  })

  it('leads with the first blocker and lists replies, holds and backups when opened', () => {
    mock(
      snapshot({
        clear: false,
        blocking: [
          'codex:aaaaaa objected: mid migration',
          'unit restic-backup.service running',
        ],
        agents: [
          {
            agent: 'codex:aaaaaa',
            provider: 'codex',
            project: 'agent-hub',
            source: 'coordination',
          },
        ],
        handshakes: [
          {
            id: 'abc123',
            to: 'codex:aaaaaa',
            from: 'cc:111111',
            state: 'acked',
            reply: 'no',
            acked_by: 'codex:aaaaaa',
            note: 'mid migration',
            eta_until: null,
            eta_running: false,
            created: new Date().toISOString(),
          },
        ],
        holds: [
          {
            project: 'summitflow',
            holder: 'cc:222222',
            kind: 'op',
            purpose: null,
            since: '',
          },
        ],
        backups: {
          summitflow: [],
          units: ['restic-backup.service'],
          processes: [],
        },
      }),
    )
    render(<HostDisruptionCard />)
    expect(
      screen.getByText(
        'Not now: codex:aaaaaa objected: mid migration (+1 more)',
      ),
    ).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /restart or reboot/i }))
    expect(
      screen.getByText('codex:aaaaaa said no: mid migration'),
    ).toBeInTheDocument()
    expect(screen.getByText(/deploy running/)).toBeInTheDocument()
    expect(screen.getAllByText('restic-backup.service').length).toBeGreaterThan(
      0,
    )
  })

  it("says it can't tell when a part could not be read", () => {
    mock(snapshot({ clear: false, unknown: ['process table unreadable'] }))
    render(<HostDisruptionCard />)
    expect(
      screen.getByText("Can't tell: process table unreadable"),
    ).toBeInTheDocument()
  })
})
