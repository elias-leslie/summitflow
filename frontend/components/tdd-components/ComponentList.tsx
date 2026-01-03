"use client";

import { useState, useMemo } from "react";
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  ChevronDown,
  ChevronRight,
  AlertTriangle,
  Clock,
} from "lucide-react";

import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import type { TddComponent, TddCapability } from "@/lib/api";

interface ComponentListProps {
  components: TddComponent[];
  capabilities: TddCapability[];
  isLoading: boolean;
  onSelectCapability: (capability: TddCapability) => void;
}

interface ComponentGroup {
  component: TddComponent;
  capabilities: TddCapability[];
  stats: {
    passing: number;
    failing: number;
    pending: number;
  };
}

function ComponentListSkeleton() {
  return (
    <div className="space-y-3">
      {[...Array(3)].map((_, i) => (
        <div key={i} className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
          <div className="flex items-center gap-3 mb-3">
            <Skeleton className="h-5 w-5 rounded" />
            <Skeleton className="h-5 w-32" />
            <Skeleton className="h-5 w-16" />
          </div>
          <div className="space-y-2 pl-8">
            {[...Array(4)].map((_, j) => (
              <Skeleton key={j} className="h-10 w-full" />
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    passing: "bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30",
    tests_passing: "bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30",
    failing: "bg-rose-500/20 text-rose-400 border-rose-500/30",
    pending: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    not_implemented: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  return colors[status] || colors.pending;
}

function getStatusIcon(status: string) {
  if (status === "tests_passing") {
    return <CheckCircle2 className="h-4 w-4 text-phosphor-400" />;
  }
  if (status === "failing") {
    return <XCircle className="h-4 w-4 text-rose-400" />;
  }
  return <HelpCircle className="h-4 w-4 text-slate-500" />;
}

function getPriorityColor(priority: number): string {
  const colors: Record<number, string> = {
    1: "bg-rose-500/20 text-rose-400 border-rose-500/30",
    2: "bg-orange-500/20 text-orange-400 border-orange-500/30",
    3: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    4: "bg-blue-500/20 text-blue-400 border-blue-500/30",
    5: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  return colors[priority] || colors[3];
}

export function ComponentList({
  components,
  capabilities,
  isLoading,
  onSelectCapability,
}: ComponentListProps) {
  const [expandedComponents, setExpandedComponents] = useState<Set<number>>(new Set());

  // Group capabilities by component
  const groupedData = useMemo<ComponentGroup[]>(() => {
    return components.map((component) => {
      const compCapabilities = capabilities.filter((c) => c.component_id === component.id);
      const stats = {
        passing: compCapabilities.filter((c) => c.status === "tests_passing").length,
        failing: compCapabilities.filter((c) => c.status === "failing").length,
        pending: compCapabilities.filter((c) => c.status === "pending" || c.status === "not_implemented").length,
      };
      return {
        component,
        capabilities: compCapabilities.sort((a, b) => a.priority - b.priority || a.name.localeCompare(b.name)),
        stats,
      };
    }).sort((a, b) => a.component.priority - b.component.priority || a.component.name.localeCompare(b.component.name));
  }, [components, capabilities]);

  const toggleComponent = (componentId: number) => {
    setExpandedComponents((prev) => {
      const next = new Set(prev);
      if (next.has(componentId)) {
        next.delete(componentId);
      } else {
        next.add(componentId);
      }
      return next;
    });
  };

  if (isLoading) return <ComponentListSkeleton />;

  if (components.length === 0) {
    return (
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-8 text-center">
        <AlertTriangle className="mx-auto h-12 w-12 text-slate-600" />
        <p className="mt-4 text-sm text-slate-500">No components found. Accept specs to create components.</p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      {groupedData.map((group) => {
        const isExpanded = expandedComponents.has(group.component.id);

        return (
          <div
            key={group.component.id}
            className="rounded-lg border border-slate-700 bg-slate-900/50 overflow-hidden"
          >
            {/* Component Header */}
            <div
              className="flex items-center gap-3 p-3 cursor-pointer hover:bg-slate-800/50 transition-colors"
              onClick={() => toggleComponent(group.component.id)}
            >
              {isExpanded ? (
                <ChevronDown className="h-4 w-4 text-slate-500" />
              ) : (
                <ChevronRight className="h-4 w-4 text-slate-500" />
              )}
              <span className="mono text-xs text-slate-500">{group.component.component_id}</span>
              <span className="font-medium text-white">{group.component.name}</span>
              <span className={`text-xs px-1.5 py-0.5 rounded border ${getPriorityColor(group.component.priority)}`}>
                P{group.component.priority}
              </span>
              <div className="flex-1" />
              <div className="flex items-center gap-2 text-xs">
                {group.stats.passing > 0 && (
                  <Badge variant="phosphor" className="gap-1 text-xs">
                    <CheckCircle2 className="h-3 w-3" />
                    {group.stats.passing}
                  </Badge>
                )}
                {group.stats.failing > 0 && (
                  <Badge variant="rose" className="gap-1 text-xs">
                    <XCircle className="h-3 w-3" />
                    {group.stats.failing}
                  </Badge>
                )}
                {group.stats.pending > 0 && (
                  <Badge variant="slate" className="gap-1 text-xs">
                    <Clock className="h-3 w-3" />
                    {group.stats.pending}
                  </Badge>
                )}
              </div>
            </div>

            {/* Capabilities List */}
            {isExpanded && group.capabilities.length > 0 && (
              <div className="border-t border-slate-800">
                {group.capabilities.map((capability) => (
                  <div
                    key={capability.id}
                    className="flex items-center gap-3 px-4 py-2.5 hover:bg-slate-800/30 border-b border-slate-800 last:border-b-0 cursor-pointer"
                    onClick={() => onSelectCapability(capability)}
                  >
                    {getStatusIcon(capability.status)}
                    <span className="mono text-xs text-slate-500 min-w-[80px]">
                      {capability.capability_id}
                    </span>
                    <span className="flex-1 text-sm text-slate-200">
                      {capability.name}
                    </span>
                    <span className={`text-xs px-1.5 py-0.5 rounded border ${getStatusColor(capability.status)}`}>
                      {capability.status.replace("_", " ")}
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* Empty state */}
            {isExpanded && group.capabilities.length === 0 && (
              <div className="border-t border-slate-800 p-4 text-center text-sm text-slate-500">
                No capabilities defined yet
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
