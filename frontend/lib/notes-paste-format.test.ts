import { describe, expect, it } from 'vitest'
import { formatNotePaste } from '../../packages/notes-ui/src/pasteFormat'

describe('formatNotePaste', () => {
  it('converts copied HTML tables to markdown tables', () => {
    const html =
      '<table><tr><th>Order</th><th>Repo</th></tr><tr><td>1</td><td>sha</td></tr></table>'

    expect(formatNotePaste('', html)).toBe(
      '| Order | Repo |\n| --- | --- |\n| 1 | sha |',
    )
  })

  it('converts tab-separated table blocks while preserving surrounding notes', () => {
    const pasted = [
      '## Recommended public-release order',
      '',
      'Order\tRepo\tRecommendation',
      '1\tsha\tBest cyber/security signal',
      '2\tmonkey-fight\tFast visual demo',
      '',
      'Afterward: update portfolio.',
    ].join('\n')

    expect(formatNotePaste(pasted)).toBe(
      [
        '## Recommended public-release order',
        '',
        '| Order | Repo | Recommendation |',
        '| --- | --- | --- |',
        '| 1 | sha | Best cyber/security signal |',
        '| 2 | monkey-fight | Fast visual demo |',
        '',
        'Afterward: update portfolio.',
      ].join('\n'),
    )
  })

  it('leaves normal prose untouched', () => {
    const pasted = '1. Do this\n2. Then do that\n\n```\na   b   c\n```'

    expect(formatNotePaste(pasted)).toBe(pasted)
  })
})
