import { beforeEach, describe, expect, it, vi } from 'vitest'
import { startTask } from './tasks-crud'

describe('tasks-crud startTask', () => {
  beforeEach(() => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: vi.fn().mockResolvedValue({
        id: 'task-123',
        project_id: 'agent-hub',
        status: 'queue',
      }),
    }) as unknown as typeof fetch
  })

  it('uses the execute endpoint exposed by the backend', async () => {
    await startTask('agent-hub', 'task-123', {
      agent_type: 'claude',
      model: 'sonnet',
    })

    expect(global.fetch).toHaveBeenCalledWith(
      'http://localhost:8001/api/projects/agent-hub/tasks/task-123/execute',
      expect.objectContaining({
        method: 'POST',
      }),
    )
  })
})
