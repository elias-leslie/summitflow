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
      recent_route_evidence: [
        {
          evidence_id: 'evidence-1',
          comment: 'Tighten the top spacing.',
          selector: '[data-testid="top-shell"]',
          created_at: '2026-04-23T01:00:00+00:00',
          created_by_display: 'Elias',
        },
        {
          evidence_id: 'evidence-2',
          comment: 'The action bar can be shorter.',
          selector: null,
          created_at: '2026-04-23T01:10:00+00:00',
          created_by_display: null,
        },
      ],
    },
    evidenceCount: 2,
    lastEvidenceAt: '2026-04-23T01:10:00+00:00',
    ...overrides,
  }
}

describe('PageDetail', () => {
  it('renders recent route evidence alongside the evidence summary', () => {
    render(<PageDetail entry={makeEntry()} />)

    expect(screen.getByText('Design Evidence')).toBeInTheDocument()
    expect(screen.getByText('2 Screenshots')).toBeInTheDocument()
    expect(screen.getByText('Recent feedback')).toBeInTheDocument()
    expect(screen.getByText('Tighten the top spacing.')).toBeInTheDocument()
    expect(
      screen.getByText('The action bar can be shorter.'),
    ).toBeInTheDocument()
    expect(screen.getByText('Elias')).toBeInTheDocument()
  })
})
