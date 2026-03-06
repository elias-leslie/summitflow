import { describe, expect, it } from 'vitest'
import {
  buildChatUrl,
  buildProjectTaskUrl,
  getChatProjectId,
} from './chat-routing'

describe('chat-routing', () => {
  it('uses the provided project_id from search params', () => {
    const params = new URLSearchParams('project_id=agent-hub')

    expect(getChatProjectId(params)).toBe('agent-hub')
  })

  it('falls back to the default project when project_id is missing', () => {
    expect(getChatProjectId(new URLSearchParams())).toBe('summitflow')
  })

  it('builds chat urls with project and task context', () => {
    expect(
      buildChatUrl({
        projectId: 'agent-hub',
        taskId: 'task-123',
        notificationId: 'notif-456',
      }),
    ).toBe('/chat?project_id=agent-hub&task_id=task-123&notification_id=notif-456')
  })

  it('builds project task urls without hardcoded project ids', () => {
    expect(buildProjectTaskUrl('agent-hub', 'task-123')).toBe(
      '/projects/agent-hub/tasks/task-123',
    )
  })
})
