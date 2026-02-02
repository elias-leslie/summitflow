import {
  Box,
  CheckCircle2,
  Clock,
  Code2,
  ImageIcon,
  LayoutTemplate,
  Sparkles,
  XCircle,
} from 'lucide-react'

export const statusConfig = {
  generated: {
    icon: Sparkles,
    color: 'text-blue-400',
    bg: 'bg-blue-500/10',
    label: 'Generated',
  },
  pending_approval: {
    icon: Clock,
    color: 'text-amber-400',
    bg: 'bg-amber-500/10',
    label: 'Pending Approval',
  },
  approved: {
    icon: CheckCircle2,
    color: 'text-emerald-400',
    bg: 'bg-emerald-500/10',
    label: 'Approved',
  },
  rejected: {
    icon: XCircle,
    color: 'text-rose-400',
    bg: 'bg-rose-500/10',
    label: 'Rejected',
  },
  applied: {
    icon: Box,
    color: 'text-purple-400',
    bg: 'bg-purple-500/10',
    label: 'Applied',
  },
  archived: {
    icon: Box,
    color: 'text-slate-400',
    bg: 'bg-slate-500/10',
    label: 'Archived',
  },
}

export const typeIcons = {
  component: Code2,
  page: LayoutTemplate,
  layout: LayoutTemplate,
  icon: ImageIcon,
  illustration: ImageIcon,
}
