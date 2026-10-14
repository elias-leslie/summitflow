import { describe, expect, it } from 'vitest'
import { development, repo, sourceSha } from './developmentFixtures'
import { deriveSignals, matchesFilter } from './developmentSignals'

const clean = {
  ...development,
  working_tree: { ...development.working_tree, state: 'clean', uncommitted: 0 },
  running: { ...development.running, source_commit: sourceSha, drift: false },
}
const synced = { ...repo, uncommitted: 0, ahead: 0, state: 'clean' as const }
const pending = (count: number) => ({
  ...clean,
  working_tree: { ...clean.working_tree, unpublished: count },
})

describe('development signals', () => {
  it('marks a repository whose stages all hold HEAD as needing nothing', () => {
    const signals = deriveSignals(synced, pending(0))
    expect(signals.attention).toBe(0)
    expect(signals.cells.accepted.label).toBe('HEAD')
    expect(signals.cells.running.label).toBe('HEAD')
    expect(signals.cells.published.label).toBe('synced')
    expect(matchesFilter(signals, 'attention')).toBe(false)
  })
  it('treats nightly-pending commits as expected, not as a problem', () => {
    const signals = deriveSignals(
      { ...synced, ahead: 80 },
      { ...pending(3), publication: { ...clean.publication, mode: 'nightly' } },
    )
    expect(signals.cells.published).toMatchObject({ tone: 'info', label: '↑3' })
    expect(signals.attention).toBe(0)
  })
  it('flags runtime drift, divergence and failed backups by severity', () => {
    const signals = deriveSignals(
      { ...synced, ahead: 1, behind: 2 },
      {
        ...clean,
        running: { ...development.running, drift: true },
        recovery: {
          ...clean.recovery,
          capture: { ...clean.recovery.capture, state: 'failed' },
        },
      },
    )
    expect(signals.cells.running.tone).toBe('warn')
    expect(signals.cells.published.detail).toBe('diverged')
    expect(signals.cells.backup.tone).toBe('bad')
    expect(signals.worst).toBe('bad')
    expect(signals.attention).toBe(7)
    expect(matchesFilter(signals, 'backup')).toBe(true)
    expect(matchesFilter(signals, 'source')).toBe(false)
  })
  it('never presents missing evidence as success', () => {
    const signals = deriveSignals(synced, {
      ...clean,
      accepted: {
        ...clean.accepted,
        state: 'unavailable',
        source_commit: null,
      },
      running: { ...clean.running, state: 'unavailable', source_commit: null },
    })
    expect(signals.cells.accepted).toMatchObject({
      tone: 'idle',
      label: 'none',
    })
    expect(signals.cells.running).toMatchObject({
      tone: 'idle',
      label: 'not deployed',
    })
    expect(signals.canPublish).toBe(false)
  })
})
