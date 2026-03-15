'use client'

import { useQuery } from '@tanstack/react-query'
import { dockerApi } from '@/lib/api/docker'

export function MetricsPanel() {
  const { data: metrics, isLoading } = useQuery({
    queryKey: ['docker', 'metrics'],
    queryFn: dockerApi.getMetrics,
    refetchInterval: 15_000,
  })

  return (
    <div className="rounded-lg border border-neutral-700 bg-neutral-800/30 p-4">
      <h2 className="text-sm font-medium text-white mb-4">Container Metrics</h2>

      {isLoading ? (
        <div className="space-y-2">
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-6 bg-neutral-800 rounded animate-pulse" />
          ))}
        </div>
      ) : !metrics?.length ? (
        <p className="text-sm text-neutral-500">No running containers</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="text-neutral-500 border-b border-neutral-700">
                <th className="text-left py-2 pr-3 font-medium">Service</th>
                <th className="text-right py-2 px-3 font-medium">CPU</th>
                <th className="text-right py-2 px-3 font-medium">Memory</th>
                <th className="text-right py-2 pl-3 font-medium">Mem %</th>
              </tr>
            </thead>
            <tbody>
              {metrics.map((m) => (
                <tr
                  key={m.name}
                  className="border-b border-neutral-800 hover:bg-neutral-800/50"
                >
                  <td className="py-1.5 pr-3 text-neutral-300 truncate max-w-[200px]">
                    {m.name}
                  </td>
                  <td className="py-1.5 px-3 text-right text-neutral-400">
                    {m.cpu_percent}
                  </td>
                  <td className="py-1.5 px-3 text-right text-neutral-400">
                    {m.mem_usage}
                  </td>
                  <td className="py-1.5 pl-3 text-right text-neutral-400">
                    {m.mem_percent}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
