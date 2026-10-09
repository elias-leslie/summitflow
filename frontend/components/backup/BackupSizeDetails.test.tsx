import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { BackupVerification } from '@/lib/api/backups'
import { BackupSizeDetails, BackupSizeExplanation } from './BackupSizeDetails'

const verification: BackupVerification = {
  verified: true,
  verified_at: '',
  errors: [],
  tree: {},
  total_files: 1,
  checksum: '',
  format: 'restic-v1',
  logical_bytes: 8 * 1024 ** 3,
  stored_bytes: 1024 ** 2,
}

describe('BackupSizeDetails', () => {
  it('distinguishes full contents from newly stored compressed data', () => {
    render(
      <BackupSizeDetails
        backup={{ size_bytes: 8 * 1024 ** 3, verification_json: verification }}
      />,
    )
    expect(screen.getByText('Contents:')).toBeInTheDocument()
    expect(screen.getByText('8.0 GB')).toBeInTheDocument()
    expect(screen.getByText('New storage:')).toBeInTheDocument()
    expect(screen.getByText('1.0 MB')).toBeInTheDocument()
  })

  it('preserves a measured zero and does not invent missing or invalid measurements', () => {
    const { rerender } = render(
      <BackupSizeDetails
        backup={{
          size_bytes: 0,
          verification_json: {
            ...verification,
            logical_bytes: 0,
            stored_bytes: 0,
          },
        }}
      />,
    )
    expect(screen.getAllByText('0 B')).toHaveLength(2)
    for (const stored_bytes of [undefined, null, -1, Number.NaN, Infinity]) {
      rerender(
        <BackupSizeDetails
          backup={{
            size_bytes: null,
            verification_json: {
              ...verification,
              logical_bytes: null,
              stored_bytes,
            },
          }}
        />,
      )
      expect(screen.getByText('Not recorded')).toBeInTheDocument()
      expect(screen.getByText('Unavailable')).toBeInTheDocument()
    }
  })

  it('labels legacy archive bytes without treating them as incremental storage', () => {
    render(
      <BackupSizeDetails
        backup={{ size_bytes: 1024 ** 2, verification_json: null }}
      />,
    )
    expect(screen.getByText('Archive:')).toBeInTheDocument()
    expect(screen.queryByText('Contents:')).not.toBeInTheDocument()
    expect(screen.getByText('Not recorded')).toBeInTheDocument()
  })

  it('explains the basis and limits without presenting it as disk usage', () => {
    render(<BackupSizeExplanation />)
    expect(screen.getByText(/before pruning/)).toHaveTextContent(
      'not total disk usage',
    )
  })
})
