"use client";

import {
  CheckCircle2,
  Package,
  Layers,
  Clock,
} from "lucide-react";

import type { TddComponent, TddCapability } from "@/lib/api";

interface BuildProgressProps {
  components: TddComponent[];
  capabilities: TddCapability[];
}

interface ProgressStats {
  components: {
    total: number;
    passing: number;
    failing: number;
    pending: number;
  };
  capabilities: {
    total: number;
    passing: number;
    failing: number;
    pending: number;
  };
}

export function BuildProgress({ components, capabilities }: BuildProgressProps) {
  // Calculate stats
  const stats: ProgressStats = {
    components: {
      total: components.length,
      passing: components.filter((c) => c.status === "tests_passing").length,
      failing: components.filter((c) => c.status === "failing").length,
      pending: components.filter((c) => c.status === "pending" || c.status === "not_implemented").length,
    },
    capabilities: {
      total: capabilities.length,
      passing: capabilities.filter((c) => c.status === "tests_passing").length,
      failing: capabilities.filter((c) => c.status === "failing").length,
      pending: capabilities.filter((c) => c.status === "pending" || c.status === "not_implemented").length,
    },
  };

  // Calculate overall progress percentage
  const progressPercent = stats.capabilities.total > 0
    ? Math.round((stats.capabilities.passing / stats.capabilities.total) * 100)
    : 0;

  const failingPercent = stats.capabilities.total > 0
    ? Math.round((stats.capabilities.failing / stats.capabilities.total) * 100)
    : 0;

  return (
    <div className="space-y-4">
      {/* Progress Bar */}
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
        <div className="flex items-center justify-between mb-3">
          <span className="text-sm font-medium text-slate-300">Build Progress</span>
          <span className="text-lg font-bold text-white mono">{progressPercent}%</span>
        </div>
        <div className="h-3 rounded-full bg-slate-800 overflow-hidden">
          {/* Stacked progress segments */}
          <div className="h-full flex">
            {/* Passing */}
            <div
              className="h-full bg-phosphor-500 transition-all duration-500"
              style={{ width: `${progressPercent}%` }}
            />
            {/* Failing */}
            <div
              className="h-full bg-rose-500 transition-all duration-500"
              style={{ width: `${failingPercent}%` }}
            />
          </div>
        </div>
        <div className="flex justify-between text-xs text-slate-500 mt-2">
          <span>{stats.capabilities.passing} passing</span>
          <span>{stats.capabilities.failing} failing</span>
          <span>{stats.capabilities.pending} pending</span>
        </div>
      </div>

      {/* Stats Cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
          <div className="flex items-center gap-2 text-slate-400 mb-2">
            <Package className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Components</span>
          </div>
          <div className="text-2xl font-bold text-white mono">{stats.components.total}</div>
          <div className="flex items-center gap-2 mt-1 text-xs">
            <span className="text-phosphor-400">{stats.components.passing} ok</span>
            <span className="text-slate-600">|</span>
            <span className="text-rose-400">{stats.components.failing} fail</span>
          </div>
        </div>

        <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-3">
          <div className="flex items-center gap-2 text-slate-400 mb-2">
            <Layers className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Capabilities</span>
          </div>
          <div className="text-2xl font-bold text-white mono">{stats.capabilities.total}</div>
          <div className="flex items-center gap-2 mt-1 text-xs">
            <span className="text-phosphor-400">{stats.capabilities.passing} ok</span>
            <span className="text-slate-600">|</span>
            <span className="text-rose-400">{stats.capabilities.failing} fail</span>
          </div>
        </div>

        <div className="rounded-lg border border-phosphor-500/30 bg-phosphor-500/5 p-3">
          <div className="flex items-center gap-2 text-phosphor-400 mb-2">
            <CheckCircle2 className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Passing</span>
          </div>
          <div className="text-2xl font-bold text-phosphor-400 mono">{stats.capabilities.passing}</div>
          <div className="text-xs text-slate-500 mt-1">
            {stats.capabilities.total > 0
              ? `${Math.round((stats.capabilities.passing / stats.capabilities.total) * 100)}% of total`
              : "0% of total"}
          </div>
        </div>

        <div className="rounded-lg border border-slate-500/30 bg-slate-500/5 p-3">
          <div className="flex items-center gap-2 text-slate-400 mb-2">
            <Clock className="h-4 w-4" />
            <span className="text-xs uppercase tracking-wider">Pending</span>
          </div>
          <div className="text-2xl font-bold text-slate-400 mono">{stats.capabilities.pending}</div>
          <div className="text-xs text-slate-500 mt-1">
            {stats.capabilities.total > 0
              ? `${Math.round((stats.capabilities.pending / stats.capabilities.total) * 100)}% of total`
              : "0% of total"}
          </div>
        </div>
      </div>
    </div>
  );
}
