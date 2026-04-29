import { Compass, FolderOpen, GitFork, ListTodo, Palette } from 'lucide-react'
import type { NavItemConfig } from './types'

// Project-specific navigation items (shown when project expanded)
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
    id: 'explorer',
    label: 'Explorer',
    href: '',
    icon: Compass,
    activeClasses: 'bg-teal-500/15 text-teal-400',
    inactiveClasses: 'text-slate-400 hover:bg-teal-500/10 hover:text-teal-400',
    iconActiveClasses: 'text-teal-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-teal-400',
  },
  {
    id: 'graph',
    label: 'Graph',
    href: '/graph',
    icon: GitFork,
    activeClasses: 'bg-cyan-500/15 text-cyan-400',
    inactiveClasses: 'text-slate-400 hover:bg-cyan-500/10 hover:text-cyan-400',
    iconActiveClasses: 'text-cyan-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-cyan-400',
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
