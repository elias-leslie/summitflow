import { Clock } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { CardHeader, CardTitle } from '@/components/ui/card'

interface CheckpointHeaderProps {
  agentType: string
  createdAt: string | null
}

export function CheckpointHeader({
  agentType,
  createdAt,
}: CheckpointHeaderProps) {
  const formatDate = (dateStr: string | null) => {
    if (!dateStr) return 'Unknown'
    return new Date(dateStr).toLocaleString()
  }

  return (
    <CardHeader className="pb-3">
      <div className="flex items-center justify-between">
        <CardTitle className="flex items-center gap-2 text-base">
          <Clock className="h-4 w-4 text-slate-500" />
          Checkpoint
        </CardTitle>
        <Badge variant="secondary" className="text-xs">
          {agentType}
        </Badge>
      </div>
      <div className="text-xs text-slate-500">{formatDate(createdAt)}</div>
    </CardHeader>
  )
}
