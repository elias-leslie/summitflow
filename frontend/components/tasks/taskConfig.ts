/**
 * Task configuration - Priority, Status, and Type settings
 */

import {
  Bug,
  CheckCircle2,
  Circle,
  Clock,
  ListTodo,
  Loader2,
  Package,
} from 'lucide-react'

// Priority colors and labels
export const priorityConfig: Record<number, { label: string; color: string }> =
  {
    0: { label: 'P0', color: 'text-red-500' },
    1: { label: 'P1', color: 'text-orange-500' },
    2: { label: 'P2', color: 'text-yellow-500' },
    3: { label: 'P3', color: 'text-blue-500' },
    4: { label: 'P4', color: 'text-slate-500' },
  }

// Status config
export const statusConfig: Record<
  string,
  { label: string; icon: typeof Circle; color: string }
> = {
  pending: { label: 'Pending', icon: Circle, color: 'text-blue-500' },
  running: { label: 'Running', icon: Loader2, color: 'text-yellow-500' },
  paused: { label: 'Paused', icon: Clock, color: 'text-orange-500' },
  completed: {
    label: 'Completed',
    icon: CheckCircle2,
    color: 'text-green-500',
  },
  failed: { label: 'Failed', icon: Circle, color: 'text-red-500' },
}

// Type icons
export const typeIcons: Record<string, typeof ListTodo> = {
  feature: Package,
  bug: Bug,
  task: ListTodo,
}

export function formatDate(dateStr: string | null): string {
  if (!dateStr) return '-'
  const date = new Date(dateStr)
  const now = new Date()
  const diffDays = Math.floor(
    (now.getTime() - date.getTime()) / (1000 * 60 * 60 * 24),
  )

  if (diffDays === 0) return 'Today'
  if (diffDays === 1) return 'Yesterday'
  if (diffDays < 7) return `${diffDays}d ago`
  return date.toLocaleDateString()
}
