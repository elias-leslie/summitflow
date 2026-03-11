/**
 * Explorer Constants - Type mappings, icons, and titles
 */

import {
  Database,
  FileText,
  Folder,
  Globe,
  Layers,
  Package,
  Zap,
} from 'lucide-react'
import type { ExplorerEntryType } from '@/lib/api/explorer'
import type { ExplorerType } from './types'

// Map UI type to API entry type
export const uiTypeToApiType: Record<ExplorerType, ExplorerEntryType> = {
  files: 'file',
  database: 'table',
  tasks: 'task',
  api: 'endpoint',
  pages: 'page',
  dependencies: 'dependency',
  architecture: 'architecture',
}

export const typeIcons: Record<ExplorerType, React.ReactNode> = {
  files: <Folder className="w-5 h-5" />,
  database: <Database className="w-5 h-5" />,
  tasks: <Zap className="w-5 h-5" />,
  api: <Globe className="w-5 h-5" />,
  pages: <FileText className="w-5 h-5" />,
  dependencies: <Package className="w-5 h-5" />,
  architecture: <Layers className="w-5 h-5" />,
}

export const typeTitles: Record<ExplorerType, string> = {
  files: 'Files Explorer',
  database: 'Database Tables',
  tasks: 'Scheduled Jobs',
  api: 'API Endpoints',
  pages: 'Frontend Pages',
  dependencies: 'Dependencies',
  architecture: 'Architecture',
}

export const explorerTypes: ExplorerType[] = [
  'files',
  'database',
  'tasks',
  'api',
  'pages',
  'dependencies',
  'architecture',
]
