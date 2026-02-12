'use client'

import { useQuery } from '@tanstack/react-query'

interface ServiceStatus {
  name: string
  status: 'up' | 'down' | 'unknown'
}

interface ServicesStatusBarProps {
  projectId: string
}

export function ServicesStatusBar({ projectId }: ServicesStatusBarProps) {
  // Fetch health data to determine service status
  const { data: health } = useQuery({
    queryKey: ['services-health', projectId],
    queryFn: async () => {
      try {
        const res = await fetch(`/api/health`)
        if (!res.ok) throw new Error('Failed to fetch health')
        return res.json()
      } catch {
        return null
      }
    },
    refetchInterval: 30000,
  })

  // Define services to monitor
  const services: ServiceStatus[] = [
    { name: 'SummitFlow Backend', status: health ? 'up' : 'unknown' },
    { name: 'SummitFlow Frontend', status: 'up' }, // If we can render, frontend is up
    { name: 'Worker', status: health?.worker ? 'up' : 'unknown' },
    { name: 'Agent Hub Backend', status: health?.agent_hub ? 'up' : 'unknown' },
    { name: 'Agent Hub Frontend', status: health?.agent_hub ? 'up' : 'unknown' },
    { name: 'Agent Hub Worker', status: health?.agent_hub_worker ? 'up' : 'unknown' },
    { name: 'Postgres', status: health?.postgres ? 'up' : 'unknown' },
    { name: 'Redis', status: health?.redis ? 'up' : 'unknown' },
    { name: 'Neo4j', status: health?.neo4j ? 'up' : 'unknown' },
  ]

  const getStatusColor = (status: string) => {
    switch (status) {
      case 'up':
        return 'bg-emerald-500'
      case 'down':
        return 'bg-rose-500'
      default:
        return 'bg-slate-500'
    }
  }

  return (
    <div className="card rounded-xl p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-300">Services Status</h3>
        <div className="flex items-center gap-3">
          {services.map((service) => (
            <div key={service.name} className="flex items-center gap-1.5">
              <span
                className={`w-2 h-2 rounded-full ${getStatusColor(service.status)}`}
                title={service.name}
              />
              <span className="text-xs text-slate-500 hidden xl:inline">
                {service.name.replace('SummitFlow ', '').replace('Agent Hub ', 'AH ')}
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
