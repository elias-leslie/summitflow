/**
 * TableColumns - Column definitions for database explorer
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import type { ExplorerColumn } from '../../types'

export const tableColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: 'name',
    label: 'Table',
  },
  {
    key: 'row_count',
    label: 'Rows',
    width: '100px',
    align: 'right',
  },
  {
    key: 'column_count',
    label: 'Columns',
    width: '80px',
    align: 'right',
  },
  {
    key: 'completeness_pct',
    label: 'Complete',
    width: '80px',
    align: 'right',
  },
]
