/**
 * ArchitectureColumns - Column definitions for architecture explorer
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import type { ExplorerColumn } from '../../types'

export const architectureColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: 'name',
    label: 'Module',
  },
  {
    key: 'scan_scope',
    label: 'Scope',
    width: '80px',
    align: 'center',
  },
  {
    key: 'violation_counts',
    label: 'Violations',
    width: '120px',
    align: 'center',
  },
  {
    key: 'files_analyzed',
    label: 'Files',
    width: '60px',
    align: 'center',
  },
  {
    key: 'health_status',
    label: 'Health',
    width: '80px',
    align: 'right',
  },
]
