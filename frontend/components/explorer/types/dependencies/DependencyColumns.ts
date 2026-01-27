/**
 * DependencyColumns - Column definitions for dependencies explorer
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import type { ExplorerColumn } from '../../types'

export const dependencyColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: 'name',
    label: 'Package',
  },
  {
    key: 'locked_version',
    label: 'Version',
    width: '100px',
  },
  {
    key: 'package_type',
    label: 'Type',
    width: '80px',
    align: 'center',
  },
  {
    key: 'source_files',
    label: 'Sources',
    width: '60px',
    align: 'center',
  },
  {
    key: 'vulnerabilities',
    label: 'Security',
    width: '90px',
    align: 'center',
  },
  {
    key: 'is_outdated',
    label: 'Status',
    width: '80px',
    align: 'right',
  },
]
