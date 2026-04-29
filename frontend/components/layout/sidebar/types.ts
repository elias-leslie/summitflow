import type { LucideIcon } from 'lucide-react'

export type NavItemId = 'tasks' | 'explorer' | 'graph' | 'files' | 'design'

export interface NavItemConfig {
  id: NavItemId
  label: string
  href: string
  icon: LucideIcon
  activeClasses: string
  inactiveClasses: string
  iconActiveClasses: string
  iconInactiveClasses: string
}

export const COLLAPSED_KEY = 'summitflow_sidebar_collapsed'
