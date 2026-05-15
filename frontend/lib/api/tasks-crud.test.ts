import { afterEach, describe, expect, it, vi } from 'vitest'
import { executeTasks } from './tasks-crud'

function taskResponse(taskId: string) {
  return {
    id: taskId,
    project_id: 'summitflow',
    task_type: 'task',
    status: 'pending',
    execution_mode: 'autonomous',
    autonomous: true,
  }
}

describe('executeTasks', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('queues tasks sequentially and reports per-task failures', async () => {
    const fetchMock = vi
      .spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(
        new Response(JSON.stringify(taskResponse('task-ok')), {
          status: 200,
          headers: { 'Content-Type': 'application/json' },
        }),
      )
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ detail: 'manual-only' }), {
          status: 400,
          headers: { 'Content-Type': 'application/json' },
        }),
      )

    const result = await executeTasks('summitflow', ['task-ok', 'task-blocked'])

    expect(result.queued).toEqual([taskResponse('task-ok')])
    expect(result.failed).toEqual([
      { taskId: 'task-blocked', error: 'manual-only' },
    ])
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][0]).toContain(
      '/api/projects/summitflow/tasks/task-ok/execute',
    )
    expect(fetchMock.mock.calls[1][0]).toContain(
      '/api/projects/summitflow/tasks/task-blocked/execute',
    )
  })
})
