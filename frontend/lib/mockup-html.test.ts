import { describe, expect, it } from 'vitest'
import {
  buildMockupElementPath,
  describeMockupElement,
  extractStructuredMockupAnnotations,
  summarizeMockupForWorkContext,
} from './mockup-html'

describe('mockup html helpers', () => {
  it('prefers structured annotation metadata over scanning html notes', () => {
    const annotations = extractStructuredMockupAnnotations(
      '<html><body><div class="sf-mock-note" data-sf-mock-note-text="old">old</div></body></html>',
      {
        annotations: [
          {
            id: 'ann-1',
            note: 'Make primary action clearer',
            element_path: 'main > button:nth-of-type(1)',
            element_label: 'button.primary "Save"',
          },
        ],
      },
    )

    expect(annotations).toEqual([
      expect.objectContaining({
        id: 'ann-1',
        note: 'Make primary action clearer',
        element_path: 'main > button:nth-of-type(1)',
        source: 'metadata',
      }),
    ])
  })

  it('builds compact work context without full html', () => {
    const summary = summarizeMockupForWorkContext({
      mockup_id: 'mk-123456789abc',
      name: 'Tasks page',
      version: 3,
      page_path: '/projects/summitflow/tasks',
      content: '<html><body><main>Large body</main></body></html>',
      metadata: {
        annotations: [
          {
            note: 'Remove this noisy panel',
            element_label: 'aside.panel',
          },
        ],
      },
    })

    expect(summary).toContain('Tasks page (mk-123456789abc v3)')
    expect(summary).toContain('aside.panel: Remove this noisy panel')
    expect(summary).not.toContain('<html>')
  })

  it('derives stable paths and readable labels for selected elements', () => {
    document.body.innerHTML =
      '<main><section class="task-list"><button class="primary cta">Run task</button><button>Stop</button></section></main>'
    const button = document.querySelector('button.primary') as HTMLElement

    expect(describeMockupElement(button)).toContain('button.primary.cta')
    expect(buildMockupElementPath(button)).toBe(
      'main > section.task-list > button.primary.cta:nth-of-type(1)',
    )
  })
})
