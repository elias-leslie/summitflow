import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PageDetail } from '@/components/explorer/types/pages/PageDetail'
import type { ExplorerEntry } from '@/lib/api/explorer'

function makeEntry(overrides: Partial<ExplorerEntry> = {}): ExplorerEntry {
  return {
    id: 1,
    entryType: 'page',
    path: '/design',
    name: 'Design',
    healthStatus: 'healthy',
    lastScannedAt: null,
    metadata: {
      port: 3001,
      http_status: 200,
      response_time_ms: 42,
    },
    ...overrides,
  }
}

describe('PageDetail', () => {
  it('renders page route health details', () => {
    render(<PageDetail entry={makeEntry()} />)

    expect(screen.getByText('/design')).toBeInTheDocument()
    expect(screen.getByText('3001')).toBeInTheDocument()
    expect(screen.getByText('200')).toBeInTheDocument()
    expect(screen.getByText('42ms')).toBeInTheDocument()
  })
})
