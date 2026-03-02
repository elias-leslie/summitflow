import {
  AlertCircle,
  Brain,
  Database,
  MessageSquare,
  Quote,
  Terminal,
  User,
  Zap,
} from 'lucide-react'
import type { AgentEventType } from '@/lib/api/tasks'

export interface EventConfig {
  icon: React.ReactNode
  label: string
  color: string
  bg: string
  border: string
}

export const EVENT_CONFIG: Record<AgentEventType, EventConfig> = {
  user_message: {
    icon: <User className="h-3.5 w-3.5" />,
    label: 'USER',
    color: 'text-slate-400',
    bg: 'bg-slate-800/40',
    border: 'border-l-slate-500',
  },
  assistant_message: {
    icon: <MessageSquare className="h-3.5 w-3.5" />,
    label: 'ASST',
    color: 'text-cyan-400',
    bg: 'bg-cyan-950/30',
    border: 'border-l-cyan-500',
  },
  system_message: {
    icon: <Zap className="h-3.5 w-3.5" />,
    label: 'SYS',
    color: 'text-violet-400',
    bg: 'bg-violet-950/20',
    border: 'border-l-violet-500',
  },
  thinking: {
    icon: <Brain className="h-3.5 w-3.5" />,
    label: 'THINK',
    color: 'text-amber-400',
    bg: 'bg-amber-950/20',
    border: 'border-l-amber-500',
  },
  tool_use: {
    icon: <Terminal className="h-3.5 w-3.5" />,
    label: 'TOOL',
    color: 'text-emerald-400',
    bg: 'bg-emerald-950/20',
    border: 'border-l-emerald-500',
  },
  tool_result: {
    icon: <Terminal className="h-3.5 w-3.5" />,
    label: 'RESULT',
    color: 'text-teal-400',
    bg: 'bg-teal-950/20',
    border: 'border-l-teal-500',
  },
  memory_inject: {
    icon: <Database className="h-3.5 w-3.5" />,
    label: 'MEM',
    color: 'text-pink-400',
    bg: 'bg-pink-950/20',
    border: 'border-l-pink-500',
  },
  memory_cite: {
    icon: <Quote className="h-3.5 w-3.5" />,
    label: 'CITE',
    color: 'text-rose-400',
    bg: 'bg-rose-950/20',
    border: 'border-l-rose-500',
  },
  error: {
    icon: <AlertCircle className="h-3.5 w-3.5" />,
    label: 'ERR',
    color: 'text-red-400',
    bg: 'bg-red-950/30',
    border: 'border-l-red-500',
  },
}
