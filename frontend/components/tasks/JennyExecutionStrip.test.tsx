import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { makeTask } from '@/tests/factories'
import { JennyExecutionStrip } from './JennyExecutionStrip'

describe('JennyExecutionStrip', () => {
  it('counts only tasks with trustworthy verification evidence', () => {
    render(
      <JennyExecutionStrip
        tasks={[
          makeTask({
            id: 'task-direct',
            status: 'completed',
            verification_result: {
              total: 0,
              verified: 0,
              unverified: [],
              all_verified: true,
            },
          }),
          makeTask({
            id: 'task-pipeline',
            status: 'completed',
            verification_result: {
              evidence_verified: true,
              verification_source: 'autonomous_quality_gate',
              execution_clean: true,
              subtask_count: 1,
              total_self_fix_attempts: 0,
              total_supervisor_attempts: 0,
            },
          }),
        ]}
      />,
    )

    const verifiedLabel = screen.getByText('Verified')
    expect(verifiedLabel.nextElementSibling).toHaveTextContent('1')
  })
})
