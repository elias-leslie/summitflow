import {
  Activity,
  Compass,
  ListTodo,
  Palette,
} from 'lucide-react'
import type { NavItemConfig } from './types'

// Project-specific navigation items (shown when project expanded)
export const projectNavItems: NavItemConfig[] = [
  {
    id: 'tasks',
    label: 'Tasks',
    href: '',
    icon: ListTodo,
    activeClasses: 'bg-cyan-500/15 text-cyan-400',
    inactiveClasses: 'text-slate-400 hover:bg-cyan-500/10 hover:text-cyan-400',
    iconActiveClasses: 'text-cyan-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-cyan-400',
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
    id: 'health',
    label: 'Health',
    href: '',
    icon: Activity,
    activeClasses: 'bg-purple-500/15 text-purple-400',
    inactiveClasses:
      'text-slate-400 hover:bg-purple-500/10 hover:text-purple-400',
    iconActiveClasses: 'text-purple-400',
    iconInactiveClasses: 'text-slate-500 group-hover:text-purple-400',
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
