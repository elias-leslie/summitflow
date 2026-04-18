import { describe, expect, it } from 'vitest'
import { buildUrlWithUpdatedSearchParams } from './search-params'

describe('buildUrlWithUpdatedSearchParams', () => {
  it('adds and updates params while preserving unrelated values', () => {
    const url = buildUrlWithUpdatedSearchParams(
      '/projects/summitflow',
      new URLSearchParams('tab=tasks&status=blocked'),
      { task: 'task-123', status: 'running' },
    )

    expect(url).toBe(
      '/projects/summitflow?tab=tasks&status=running&task=task-123',
    )
  })

  it('removes params and omits the query string when none remain', () => {
    const url = buildUrlWithUpdatedSearchParams(
      '/projects/summitflow',
      new URLSearchParams('task=task-123'),
      { task: null },
    )

    expect(url).toBe('/projects/summitflow')
  })
})
