import {
  AlertCircle,
  ArrowDown,
  ArrowUp,
  Check,
  GitBranch,
  type LucideIcon,
} from 'lucide-react'
import type { RepoStatus } from '@/lib/api'
import { THEME } from './theme'

export interface StateInfo {
  label: string
  icon: LucideIcon
  color: string
  bg: string
}

export function getStateInfo(state: RepoStatus['state']): StateInfo {
  switch (state) {
    case 'clean':
      return { label: 'Clean', icon: Check, color: 'text-emerald-400', bg: 'bg-emerald-500/10' }
    case 'dirty':
      return { label: 'Dirty', icon: AlertCircle, color: THEME.colors.accent.pink, bg: 'bg-pink-500/10' }
    case 'behind':
      return { label: 'Behind', icon: ArrowDown, color: THEME.colors.accent.amber, bg: 'bg-amber-500/10' }
    case 'ahead':
      return { label: 'Ahead', icon: ArrowUp, color: THEME.colors.accent.cyan, bg: 'bg-cyan-500/10' }
    default:
      return { label: state, icon: GitBranch, color: 'text-slate-400', bg: 'bg-slate-500/10' }
  }
}
