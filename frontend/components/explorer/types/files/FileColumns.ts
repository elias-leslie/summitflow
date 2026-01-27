/**
 * FileColumns - Column definitions for files explorer
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import type { ExplorerColumn } from '../../types'

export const fileColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: 'name',
    label: 'Name',
  },
  {
    key: 'lines_of_code',
    label: 'LOC',
    width: '80px',
    align: 'right',
  },
  {
    key: 'size_bytes',
    label: 'Size',
    width: '80px',
    align: 'right',
  },
  {
    key: 'last_scanned_at',
    label: 'Modified',
    width: '100px',
    align: 'right',
  },
]
