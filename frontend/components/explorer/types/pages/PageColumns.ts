/**
 * PageColumns - Column definitions for pages explorer
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import type { ExplorerColumn } from '../../types'

export const pageColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: 'name',
    label: 'Page',
  },
  {
    key: 'route_params',
    label: 'Params',
    width: '100px',
  },
  {
    key: 'http_status',
    label: 'Status',
    width: '70px',
    align: 'center',
  },
  {
    key: 'response_time_ms',
    label: 'Response',
    width: '80px',
    align: 'right',
  },
]
