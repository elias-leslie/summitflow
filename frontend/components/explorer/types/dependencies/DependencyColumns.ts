/**
 * DependencyColumns - Column definitions for dependencies explorer
 */

import type { ExplorerEntry } from '@/lib/api/explorer'
import type { ExplorerColumn } from '../../types'

export const dependencyColumns: ExplorerColumn<ExplorerEntry>[] = [
  {
    key: 'name',
    label: 'Package',
    render: () => null,
  },
  {
    key: 'locked_version',
    label: 'Version',
    width: '100px',
    render: () => null,
  },
  {
    key: 'package_type',
    label: 'Type',
    width: '80px',
    align: 'center',
    render: () => null,
  },
  {
    key: 'vulnerabilities',
    label: 'Security',
    width: '90px',
    align: 'center',
    render: () => null,
  },
  {
    key: 'is_outdated',
    label: 'Status',
    width: '80px',
    align: 'right',
    render: () => null,
  },
]
