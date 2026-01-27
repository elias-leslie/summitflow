/**
 * TaskColumns - Column definitions for tasks explorer
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import type { ExplorerColumn } from '../../types'

export const taskColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: 'name',
    label: 'Task',
  },
  {
    key: 'schedule_human',
    label: 'Schedule',
    width: '120px',
  },
  {
    key: 'success_rate_pct',
    label: 'Success',
    width: '80px',
    align: 'right',
  },
  {
    key: 'avg_duration_ms',
    label: 'Avg Time',
    width: '80px',
    align: 'right',
  },
]
