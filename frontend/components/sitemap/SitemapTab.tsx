"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  RefreshCw,
  Loader2,
  AlertCircle,
  CheckCircle2,
  AlertTriangle,
  HelpCircle,
  Compass,
  Activity,
  Globe,
  Server,
} from "lucide-react";
import {
  fetchSitemapEntries,
  fetchHealthSummary,
  triggerDiscovery,
  checkAllHealth,
  type SitemapEntry,
  type HealthStatus,
} from "@/lib/api";

interface SitemapTabProps {
  projectId: string;
}

export function SitemapTab({ projectId }: SitemapTabProps) {
  const queryClient = useQueryClient();
  const [portFilter, setPortFilter] = useState<string>("all");
  const [healthFilter, setHealthFilter] = useState<string>("all");

  // Queries
  const { data: entriesData, isLoading: entriesLoading } = useQuery({
    queryKey: ["sitemap", projectId, "entries", portFilter, healthFilter],
    queryFn: () =>
      fetchSitemapEntries(projectId, {
        port: portFilter !== "all" ? parseInt(portFilter) : undefined,
        health_status: healthFilter !== "all" ? (healthFilter as HealthStatus) : undefined,
        limit: 500,
      }),
    refetchInterval: 60000,
  });

  const { data: healthSummary } = useQuery({
    queryKey: ["sitemap", projectId, "health-summary"],
    queryFn: () => fetchHealthSummary(projectId),
    refetchInterval: 60000,
  });

  // Mutations
  const discoverMutation = useMutation({
    mutationFn: () => triggerDiscovery(projectId),
    onSuccess: (result) => {
      alert(`Discovery complete: ${result.backend_discovered} backend, ${result.frontend_discovered} frontend`);
      setTimeout(() => queryClient.invalidateQueries({ queryKey: ["sitemap", projectId] }), 2000);
    },
    onError: (e) => alert(`Discovery failed: ${e}`),
  });

  const checkAllMutation = useMutation({
    mutationFn: () => checkAllHealth(projectId),
    onSuccess: (result) => {
      alert(`Health check complete: ${result.healthy} healthy, ${result.warning} warning, ${result.error} error`);
      queryClient.invalidateQueries({ queryKey: ["sitemap", projectId] });
    },
    onError: (e) => alert(`Health check failed: ${e}`),
  });

  // Health indicator
  const HealthIcon = ({ status }: { status: string }) => {
    const className = "w-4 h-4";
    switch (status) {
      case "healthy":
        return <CheckCircle2 className={`${className} text-green-500`} />;
      case "warning":
        return <AlertTriangle className={`${className} text-yellow-500`} />;
      case "error":
        return <AlertCircle className={`${className} text-red-500`} />;
      default:
        return <HelpCircle className={`${className} text-slate-500`} />;
    }
  };

  // Get unique ports
  const uniquePorts = entriesData?.entries
    ? [...new Set(entriesData.entries.map((e) => e.port))].sort()
    : [];

  return (
    <div className="space-y-4">
      {/* Summary Cards */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
        <div className="card p-4">
          <div className="text-xs text-slate-400">Total</div>
          <div className="text-2xl font-bold text-white tabular-nums">{healthSummary?.total || 0}</div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3 text-green-500" />
            <span className="text-xs text-slate-400">Healthy</span>
          </div>
          <div className="text-2xl font-bold text-green-500 tabular-nums">{healthSummary?.healthy || 0}</div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <AlertTriangle className="h-3 w-3 text-yellow-500" />
            <span className="text-xs text-slate-400">Warnings</span>
          </div>
          <div className="text-2xl font-bold text-yellow-500 tabular-nums">{healthSummary?.warning || 0}</div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <AlertCircle className="h-3 w-3 text-red-500" />
            <span className="text-xs text-slate-400">Errors</span>
          </div>
          <div className="text-2xl font-bold text-red-500 tabular-nums">{healthSummary?.error || 0}</div>
        </div>
        <div className="card p-4">
          <div className="flex items-center gap-1">
            <HelpCircle className="h-3 w-3 text-slate-500" />
            <span className="text-xs text-slate-400">Unknown</span>
          </div>
          <div className="text-2xl font-bold text-slate-500 tabular-nums">{healthSummary?.unknown || 0}</div>
        </div>
      </div>

      {/* Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        {/* Port filter */}
        <select
          value={portFilter}
          onChange={(e) => setPortFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-white"
        >
          <option value="all">All Ports</option>
          {uniquePorts.map((port) => (
            <option key={port} value={String(port)}>
              :{port}
            </option>
          ))}
        </select>

        {/* Health filter */}
        <select
          value={healthFilter}
          onChange={(e) => setHealthFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-1.5 text-sm text-white"
        >
          <option value="all">All Status</option>
          <option value="healthy">Healthy</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="unknown">Unknown</option>
        </select>

        <div className="flex-1" />

        {/* Check All Health */}
        <button
          onClick={() => checkAllMutation.mutate()}
          disabled={checkAllMutation.isPending}
          className="btn-secondary text-sm flex items-center gap-2"
        >
          {checkAllMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Activity className="h-4 w-4" />
          )}
          Check All
        </button>

        {/* Discover */}
        <button
          onClick={() => discoverMutation.mutate()}
          disabled={discoverMutation.isPending}
          className="btn-primary text-sm flex items-center gap-2"
        >
          {discoverMutation.isPending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Compass className="h-4 w-4" />
          )}
          Discover
        </button>
      </div>

      {/* Content */}
      {entriesLoading ? (
        <div className="flex items-center justify-center py-12">
          <Loader2 className="h-8 w-8 animate-spin text-slate-400" />
        </div>
      ) : !entriesData?.entries.length ? (
        <div className="flex flex-col items-center justify-center py-12 text-slate-400">
          <Compass className="h-12 w-12 mb-4 opacity-50" />
          <p className="text-sm">No sitemap entries found</p>
          <p className="text-xs mt-1">Click &quot;Discover&quot; to scan for endpoints</p>
        </div>
      ) : (
        <div className="card overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-slate-800/50">
              <tr>
                <th className="text-left p-3 text-slate-400 font-medium">Status</th>
                <th className="text-left p-3 text-slate-400 font-medium">Port</th>
                <th className="text-left p-3 text-slate-400 font-medium">Path</th>
                <th className="text-left p-3 text-slate-400 font-medium">Method</th>
                <th className="text-left p-3 text-slate-400 font-medium">Type</th>
                <th className="text-right p-3 text-slate-400 font-medium">Response</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {entriesData.entries.map((entry) => (
                <tr key={entry.id} className="hover:bg-slate-800/30 transition-colors">
                  <td className="p-3">
                    <HealthIcon status={entry.health_status} />
                  </td>
                  <td className="p-3">
                    <span className="mono text-phosphor-400">:{entry.port}</span>
                  </td>
                  <td className="p-3">
                    <span className="mono text-white">{entry.path}</span>
                    {entry.title && (
                      <span className="ml-2 text-slate-500 text-xs">{entry.title}</span>
                    )}
                  </td>
                  <td className="p-3">
                    <span
                      className={`mono text-xs px-1.5 py-0.5 rounded ${
                        entry.method === "GET"
                          ? "bg-green-500/20 text-green-400"
                          : entry.method === "POST"
                          ? "bg-blue-500/20 text-blue-400"
                          : entry.method === "DELETE"
                          ? "bg-red-500/20 text-red-400"
                          : "bg-slate-500/20 text-slate-400"
                      }`}
                    >
                      {entry.method}
                    </span>
                  </td>
                  <td className="p-3">
                    <span className="flex items-center gap-1.5 text-slate-400">
                      {entry.entry_type === "frontend_page" ? (
                        <Globe className="w-3.5 h-3.5" />
                      ) : (
                        <Server className="w-3.5 h-3.5" />
                      )}
                      <span className="text-xs">{entry.entry_type}</span>
                    </span>
                  </td>
                  <td className="p-3 text-right">
                    {entry.response_time_ms !== null && (
                      <span className="mono text-xs text-slate-400 tabular-nums">
                        {entry.response_time_ms}ms
                      </span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
