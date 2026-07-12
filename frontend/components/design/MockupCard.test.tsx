import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Mockup } from '@/lib/api/mockups'
import { buildThumbnailSrcDoc, MockupCard } from './MockupCard'

const HTML_MOCKUP: Mockup = {
  id: 1,
  project_id: 'summitflow',
  mockup_id: 'mockup-1',
  name: 'Unsafe preview',
  description: null,
  mockup_type: 'page',
  file_path: null,
  content:
    '<!doctype html><script>window.top.location="https://attacker.invalid"</script><img src="https://attacker.invalid/pixel">',
  status: 'generated',
  approved_at: null,
  approved_by: null,
  applied_at: null,
  task_id: null,
  page_path: null,
  version: 1,
  parent_mockup_id: null,
  generator: null,
  generation_prompt: null,
  generation_time_ms: null,
  iteration_count: 0,
  created_at: null,
  updated_at: null,
  rating_average: 0,
  rating_count: 0,
  user_rating: 0,
  comment_count: 0,
}

describe('MockupCard HTML preview isolation', () => {
  it('places a deny-by-default CSP before untrusted preview markup', () => {
    const document = buildThumbnailSrcDoc(HTML_MOCKUP.content ?? '')

    expect(document).toContain("default-src 'none'")
    expect(document.indexOf('Content-Security-Policy')).toBeLessThan(
      document.indexOf('attacker.invalid'),
    )
  })

  it('renders HTML previews in an empty sandbox', () => {
    render(
      <MockupCard
        mockup={HTML_MOCKUP}
        viewMode="grid"
        onClick={vi.fn()}
        onRate={vi.fn()}
      />,
    )

    expect(screen.getByTitle('Unsafe preview')).toHaveAttribute('sandbox', '')
  })
})
