import { ArrowDown, ArrowUp, CheckCircle2, FileEdit } from 'lucide-react'
import type { ReactNode } from 'react'
import type { RepoStatus } from '@/lib/api'

export function getStateColor(state: RepoStatus['state']): string {
  switch (state) {
    case 'clean':
      return 'phosphor'
    case 'dirty':
      return 'outrun'
    case 'behind':
      return 'amber'
    case 'ahead':
      return 'sunset'
    default:
      return 'slate'
  }
}

export function getStateIcon(state: RepoStatus['state']): ReactNode {
  switch (state) {
    case 'clean':
      return <CheckCircle2 className="w-4 h-4" />
    case 'dirty':
      return <FileEdit className="w-4 h-4" />
    case 'behind':
      return <ArrowDown className="w-4 h-4" />
    case 'ahead':
      return <ArrowUp className="w-4 h-4" />
    default:
      return null
  }
}

export function getStateLabel(state: RepoStatus['state']): string {
  switch (state) {
    case 'clean':
      return 'Synced'
    case 'dirty':
      return 'Modified'
    case 'behind':
      return 'Behind'
    case 'ahead':
      return 'Ahead'
    default:
      return state
  }
}

export function getStateHexColor(stateColor: string): string {
  switch (stateColor) {
    case 'phosphor':
      return '#00f5ff'
    case 'outrun':
      return '#ff0066'
    case 'amber':
      return '#fbbf24'
    case 'sunset':
      return '#ff6600'
    default:
      return '#64748b'
  }
}
