import { FolderOpen, ListTodo, Palette } from 'lucide-react'
import type { NavItemConfig } from './types'

// Project-specific navigation items (shown when project expanded).
// Graph is frozen: its route stays reachable by URL, but it is no longer
// offered in the sidebar.
export const projectNavItems: NavItemConfig[] = [
  {
    id: 'tasks',
    label: 'Tasks',
    href: '',
    icon: ListTodo,
    activeClasses: 'bg-phosphor-500/15 text-phosphor-400',
    inactiveClasses:
      'text-slate-400 hover:bg-phosphor-500/10 hover:text-phosphor-400',
    iconActiveClasses: 'text-phosphor-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-phosphor-400',
  },
  {
    id: 'files',
    label: 'Files',
    href: '/files',
    icon: FolderOpen,
    activeClasses: 'bg-emerald-500/15 text-emerald-400',
    inactiveClasses:
      'text-slate-400 hover:bg-emerald-500/10 hover:text-emerald-400',
    iconActiveClasses: 'text-emerald-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-emerald-400',
  },
  {
    id: 'design',
    label: 'Design',
    href: '/design',
    icon: Palette,
    activeClasses: 'bg-fuchsia-500/15 text-fuchsia-400',
    inactiveClasses:
      'text-slate-400 hover:bg-fuchsia-500/10 hover:text-fuchsia-400',
    iconActiveClasses: 'text-fuchsia-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-fuchsia-400',
  },
]
