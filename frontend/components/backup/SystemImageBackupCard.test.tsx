import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { SystemImageBackupCard } from './SystemImageBackupCard'

vi.mock('@/lib/api/backups', () => ({
  startSystemImageBackup: vi.fn(),
  stopSystemImageBackup: vi.fn(),
}))

const pendingStatus = {
  installed: true,
  version: '6.3.2.1307',
  service_active: true,
  secure_boot_enabled: true,
  mok_enrolled: false,
  mok_enrollment_pending: true,
  module_loaded: false,
  module_signer: 'davion-sidarli Secure Boot Module Signature key',
  repository_name: 'SummitFlowSystemImage',
  repository_path:
    '/media/kasadis/Backups/davion-gem/system-images/davion-sidarli-linux',
  repository_accessible: true,
  job_name: 'SummitFlowSystemImage',
  job_configured: true,
  job_id: 'job-1',
  schedule_summary: 'Daily at 02:00; Active full Every Sun.',
  protected_objects: ['/dev/nvme0n1p7', '/dev/nvme0n1p5', '/dev/nvme0n1p1'],
  last_session: {
    id: 'session-1',
    job_name: 'SummitFlowSystemImage',
    session_type: 'Backup',
    state: 'Failed',
    created_at: '2026-05-07 10:18',
    started_at: '2026-05-07 10:18',
    finished_at: '2026-05-07 10:18',
  },
  active_session: null,
  can_start: false,
  blocked_reason: 'Secure Boot is waiting for MOK enrollment at next reboot.',
  next_action: 'Secure Boot is waiting for MOK enrollment at next reboot.',
}

describe('SystemImageBackupCard', () => {
  it('summarizes pending Secure Boot enrollment while collapsed', () => {
    render(
      <SystemImageBackupCard
        status={pendingStatus}
        isLoading={false}
        onRefresh={() => {}}
      />,
    )

    expect(screen.getByText('System Image')).toBeInTheDocument()
    expect(screen.getByText('Reboot Required')).toBeInTheDocument()
    expect(
      screen.getAllByText(
        'Secure Boot is waiting for MOK enrollment at next reboot.',
      ).length,
    ).toBeGreaterThan(0)
  })

  it('shows repository, protected volumes, and disabled start after expanding', () => {
    render(
      <SystemImageBackupCard
        status={pendingStatus}
        isLoading={false}
        onRefresh={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /system image/i }))

    expect(screen.getByText('SummitFlowSystemImage')).toBeInTheDocument()
    expect(screen.getByText('/dev/nvme0n1p7')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /start/i })).toBeDisabled()
  })
})
