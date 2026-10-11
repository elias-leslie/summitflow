import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BackupHealthItem, BackupHealthResponse } from '@/lib/api/backups'
import { StatusRibbon } from './StatusRibbon'

function source(
  id: string,
  enabled: boolean,
  health_status: string,
): BackupHealthItem {
  return {
    source_id: id,
    source_name: id,
    enabled,
    health_status,
    offsite_status: 'verified',
  } as BackupHealthItem
}

describe('Backup status ribbon', () => {
  it('counts enabled sources and keeps disabled ones out of the health bar', () => {
    const health = {
      sources: [
        source('a', true, 'green'),
        source('b', true, 'yellow'),
        source('c', false, 'disabled'),
      ],
      pending_upload_count: 0,
    } as unknown as BackupHealthResponse

    const { container } = render(
      <StatusRibbon
        health={health}
        storageSummary={undefined}
        storageStatus={undefined}
        isLoading={false}
      />,
    )

    expect(screen.getByText('sources').previousSibling).toHaveTextContent('2')
    expect(screen.getByText('disabled').previousSibling).toHaveTextContent('1')
    expect(container.querySelectorAll('[title]')).toHaveLength(2)
    expect(screen.queryByTitle('c: disabled')).not.toBeInTheDocument()
  })
})
