import {
  AlertTriangle,
  Archive,
  ArrowDownCircle,
  Bug,
  CheckSquare,
  GitBranch,
  LayoutGrid,
  MessageSquare,
  Package,
  RefreshCw,
} from 'lucide-react'
import type { TaskType } from '@/lib/api'

export const SUMMITFLOW_PROJECT_ID = 'summitflow'

export const LOGO_WIDE_WIDTH = 200
export const LOGO_HEIGHT = 56
export const LOGO_SQUARE_SIZE = 56
export const LOGO_CONTAINER_WIDTH = 220
export const LOGO_SHIFT_COLLAPSED = 72

export const typeIcons: Record<TaskType, React.ReactNode> = {
  feature: <Package className="h-3.5 w-3.5 text-purple-400" />,
  bug: <Bug className="h-3.5 w-3.5 text-rose-400" />,
  task: <CheckSquare className="h-3.5 w-3.5 text-blue-400" />,
  refactor: <RefreshCw className="h-3.5 w-3.5 text-cyan-400" />,
  debt: <AlertTriangle className="h-3.5 w-3.5 text-amber-400" />,
  regression: <ArrowDownCircle className="h-3.5 w-3.5 text-orange-400" />,
}

export const navItems = [
  {
    id: 'dashboard',
    label: 'Dashboard',
    href: '/',
    icon: LayoutGrid,
    activeColor: 'outrun',
  },
  {
    id: 'git',
    label: 'Git',
    href: '/git',
    icon: GitBranch,
    activeColor: 'violet',
  },
  {
    id: 'backups',
    label: 'Backups',
    href: '/backups',
    icon: Archive,
    activeColor: 'indigo',
  },
  {
    id: 'chat',
    label: 'Chat',
    href: 'https://agent.summitflow.dev/chat',
    icon: MessageSquare,
    activeColor: 'indigo',
    external: true,
  },
] as const
