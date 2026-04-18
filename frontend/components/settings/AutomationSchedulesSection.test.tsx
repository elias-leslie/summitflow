import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import { AutomationSchedulesSection } from './AutomationSchedulesSection'

describe('AutomationSchedulesSection', () => {
  it('renders every schedule with toggle state and calls the toggle handler', () => {
    const onToggle = vi.fn()
    render(
      <AutomationSchedulesSection
        projectId="summitflow"
        schedules={[
          {
            schedule_id: 'work_pickup',
            config_key: 'work_pickup_enabled',
            label: 'Autonomous work pickup',
            description: 'Dispatches pending autonomous tasks.',
            cron: '15 */2 * * *',
            scope: 'project',
            default_enabled: true,
            enabled: true,
            managed_project_id: 'summitflow',
          },
          {
            schedule_id: 'health_monitor',
            config_key: 'health_monitor_enabled',
            label: 'Health monitor',
            description: 'Performs frequent health checks.',
            cron: '*/5 * * * *',
            scope: 'system',
            default_enabled: true,
            enabled: false,
            managed_project_id: 'summitflow',
          },
        ]}
        updatingScheduleId={null}
        onToggle={onToggle}
      />,
    )

    expect(screen.getByText('Autonomous work pickup')).toBeInTheDocument()
    expect(screen.getByText('Health monitor')).toBeInTheDocument()
    expect(screen.getByText('Project')).toBeInTheDocument()
    expect(screen.getByText('System')).toBeInTheDocument()

    fireEvent.click(
      screen.getByRole('switch', { name: 'Disable Autonomous work pickup' }),
    )
    expect(onToggle).toHaveBeenCalledWith(
      expect.objectContaining({ schedule_id: 'work_pickup' }),
    )
  })
})
