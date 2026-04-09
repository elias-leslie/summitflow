import { fireEvent, render, screen } from '@testing-library/react'
import type { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { SetupChecklist } from './SetupChecklist'

vi.mock('next/link', () => ({
  default: ({
    href,
    children,
    ...props
  }: {
    href: string
    children: ReactNode
  }) => (
    <a href={href} {...props}>
      {children}
    </a>
  ),
}))

vi.mock('@/lib/api/backups', () => ({
  createBackupSource: vi.fn(),
  createSourceBackup: vi.fn(),
  updateBackupSource: vi.fn(),
}))

describe('SetupChecklist', () => {
  it('starts collapsed and shows a progress summary line', () => {
    render(
      <SetupChecklist
        storageStatus={undefined}
        sources={[]}
        healthItems={[]}
        isLoading={false}
        onSourceChanged={() => {}}
        onBackupTriggered={() => {}}
      />,
    )

    expect(screen.getByText('0 of 4 complete. 4 steps still need attention.')).toBeInTheDocument()
    expect(screen.queryByText('Remote storage')).not.toBeInTheDocument()
  })

  it('reveals setup steps after expanding the checklist', () => {
    render(
      <SetupChecklist
        storageStatus={undefined}
        sources={[]}
        healthItems={[]}
        isLoading={false}
        onSourceChanged={() => {}}
        onBackupTriggered={() => {}}
      />,
    )

    fireEvent.click(screen.getByRole('button', { name: /set up backup protection/i }))

    expect(screen.getByText('Remote storage')).toBeInTheDocument()
    expect(screen.getByText('Backup sources')).toBeInTheDocument()
  })
})
