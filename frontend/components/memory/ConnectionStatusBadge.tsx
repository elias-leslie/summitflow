'use client'

import { RefreshCw, WifiOff, Zap } from 'lucide-react'
import { Badge } from '../ui/badge'

export type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected'

export interface ConnectionStatusBadgeProps {
  status: ConnectionStatus
}

export function ConnectionStatusBadge({ status }: ConnectionStatusBadgeProps) {
  if (status === 'connected') {
    return (
      <Badge
        variant="outline"
        className="bg-emerald-500/10 text-emerald-500 text-xs"
      >
        <Zap className="h-3 w-3 mr-1" />
        Live
      </Badge>
    )
  }

  if (status === 'reconnecting') {
    return (
      <Badge
        variant="outline"
        className="bg-amber-500/10 text-amber-500 text-xs"
      >
        <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
        Reconnecting
      </Badge>
    )
  }

  return (
    <Badge variant="outline" className="bg-red-500/10 text-red-500 text-xs">
      <WifiOff className="h-3 w-3 mr-1" />
      Disconnected
    </Badge>
  )
}
