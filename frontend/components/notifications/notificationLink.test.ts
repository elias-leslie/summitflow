import { describe, expect, it } from 'vitest'
import type { Notification } from '@/lib/api/notifications'
import { notificationHref } from './notificationLink'

const base: Notification = {
  id: 'n1',
  project_id: 'summitflow',
  task_id: null,
  type: 'system',
  title: 't',
  message: 'm',
  severity: 'info',
  status: 'pending',
  metadata: {},
  created_at: null,
  read_at: null,
  dismissed_at: null,
}

describe('notificationHref', () => {
  it.each([
    [{ metadata: { url: '/backups/stb-1' } }, '/backups/stb-1'],
    [{ metadata: { url: '//evil.example' } }, null],
    [{ metadata: { url: 'https://evil.example' } }, null],
    [
      { task_id: 'task-1', project_id: 'agent-hub' },
      '/projects/agent-hub?task=task-1',
    ],
    [{ metadata: { nightly_publication: true } }, '/git'],
    [{ metadata: { backup_alert: 'safety:restic_checks' } }, '/backups'],
    [{ metadata: { dedupe_key: 'backup-alert:x:recovered:t' } }, '/backups'],
    [
      { metadata: { operation: 'local-integrity', backend_id: 'stb-1' } },
      '/backups',
    ],
    [{ metadata: { health_transition: 'ok->degraded' } }, '/runtime'],
    [{ metadata: { dedupe_key: 'audit-telegram-test' } }, null],
  ])('%j -> %s', (patch, expected) => {
    expect(notificationHref({ ...base, ...patch } as Notification)).toBe(
      expected,
    )
  })
})
