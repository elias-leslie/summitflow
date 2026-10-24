import { render, screen, within } from '@testing-library/react'
import { afterAll, beforeAll, describe, expect, it, vi } from 'vitest'
import {
  checked,
  health,
  host,
  hoursAgo,
  item,
  now,
} from '@/lib/backup-status.fixtures'
import { MachineBackupCard } from './MachineBackupCard'
import { OffsiteCard } from './OffsiteCard'

beforeAll(() => {
  vi.useFakeTimers()
  vi.setSystemTime(now)
})
afterAll(() => {
  vi.useRealTimers()
})

describe('MachineBackupCard', () => {
  it('marks the block amber and says "Not yet tested" before any restore test', () => {
    render(
      <MachineBackupCard
        status={host()}
        schedule={{ window: '02:00-06:00' }}
        isLoading={false}
        onRefresh={() => {}}
      />,
    )
    const block = screen.getByTestId('machine-backup')
    expect(block).toHaveAttribute('data-tone', 'warn')
    expect(within(block).getByText('Not yet tested')).toBeInTheDocument()
    expect(within(block).getByText('Nightly from 02:00')).toBeInTheDocument()
  })

  it('turns red when the last good backup is older than a night', () => {
    render(
      <MachineBackupCard
        status={host({
          restore_verified: true,
          restore_test_result: 'verified',
          restore_tested_at: hoursAgo(48),
          last_good_result: {
            status: 'completed',
            started_at: hoursAgo(50),
            finished_at: hoursAgo(49.9),
          },
        })}
        schedule={{ window: '02:00-06:00' }}
        isLoading={false}
        onRefresh={() => {}}
      />,
    )
    expect(screen.getByTestId('machine-backup')).toHaveAttribute(
      'data-tone',
      'bad',
    )
  })
})

describe('OffsiteCard', () => {
  it('links each failing source to its page', () => {
    render(
      <OffsiteCard
        health={health([
          item({}),
          item({
            source_id: 'owner-chrome',
            source_name: 'Owner Chrome profile',
            health_status: 'red',
          }),
        ])}
        destinations={{
          schedule_window: null,
          schedule_timezone: 'UTC',
          local_check: checked,
          drive_check: checked,
          check_alerts: [],
          proxmox: null,
        }}
        isLoading={false}
        onRefresh={() => {}}
      />,
    )
    const block = screen.getByTestId('offsite-copies')
    expect(block).toHaveAttribute('data-tone', 'bad')
    expect(
      within(block).getByRole('link', { name: 'Owner Chrome profile' }),
    ).toHaveAttribute('href', '/backups/owner-chrome')
    const order = within(
      within(block).getByRole('list', { name: 'Copies in order' }),
    )
      .getAllByRole('listitem')
      .map((row) => row.textContent ?? '')
    expect(order[0]).toMatch(/^T7/)
    expect(order[1]).toMatch(/Google Drive/)
  })
})
