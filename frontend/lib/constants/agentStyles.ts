/**
 * Agent styling configuration for chat UI.
 * Defines colors, icons, and display names for each agent type.
 */

import type { LucideIcon } from 'lucide-react'
import { Bot, Sparkles, User } from 'lucide-react'

export type AgentType = 'user' | 'claude' | 'gemini'

export interface AgentStyle {
  name: string
  icon: LucideIcon
  bgColor: string
  textColor: string
  borderColor: string
  iconBg: string
}

export const AGENT_STYLES: Record<AgentType, AgentStyle> = {
  user: {
    name: 'You',
    icon: User,
    bgColor: 'bg-slate-800/50',
    textColor: 'text-slate-200',
    borderColor: 'border-slate-700',
    iconBg: 'bg-slate-700',
  },
  claude: {
    name: 'Claude',
    icon: Sparkles,
    bgColor: 'bg-amber-950/30',
    textColor: 'text-amber-200',
    borderColor: 'border-amber-900/50',
    iconBg: 'bg-amber-900/50',
  },
  gemini: {
    name: 'Gemini',
    icon: Bot,
    bgColor: 'bg-blue-950/30',
    textColor: 'text-blue-200',
    borderColor: 'border-blue-900/50',
    iconBg: 'bg-blue-900/50',
  },
}
