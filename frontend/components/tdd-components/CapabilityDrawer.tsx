"use client";

import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  CheckCircle2,
  XCircle,
  HelpCircle,
  Lock,
  Unlock,
  FlaskConical,
  Link2,
  Timer,
} from "lucide-react";

import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
  SheetClose,
  SheetBody,
} from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  fetchTddCapability,
  lockTddCapability,
  type TddCapability,
  type TddCapabilityWithTests,
} from "@/lib/api";

interface CapabilityDrawerProps {
  capability: TddCapability | null;
  projectId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

function getStatusColor(status: string): string {
  const colors: Record<string, string> = {
    passing: "bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30",
    failing: "bg-rose-500/20 text-rose-400 border-rose-500/30",
    pending: "bg-amber-500/20 text-amber-400 border-amber-500/30",
    not_implemented: "bg-slate-500/20 text-slate-400 border-slate-500/30",
  };
  return colors[status] || colors.pending;
}

function getStatusIcon(status: string, size: "sm" | "md" = "sm") {
  const sizeClass = size === "sm" ? "h-4 w-4" : "h-5 w-5";
  if (status === "passing") {
    return <CheckCircle2 className={`${sizeClass} text-phosphor-400`} />;
  }
  if (status === "failing") {
    return <XCircle className={`${sizeClass} text-rose-400`} />;
  }
  return <HelpCircle className={`${sizeClass} text-slate-500`} />;
}

function getTestResultIcon(result: string | null) {
  if (result === "passed") {
    return <CheckCircle2 className="h-3.5 w-3.5 text-phosphor-400" />;
  }
  if (result === "failed" || result === "error") {
    return <XCircle className="h-3.5 w-3.5 text-rose-400" />;
  }
  if (result === "timeout") {
    return <Timer className="h-3.5 w-3.5 text-amber-400" />;
  }
  return <HelpCircle className="h-3.5 w-3.5 text-slate-500" />;
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

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  return new Date(dateStr).toLocaleString();
}

export function CapabilityDrawer({
  capability,
  projectId,
  open,
  onOpenChange,
}: CapabilityDrawerProps) {
  const queryClient = useQueryClient();
  const [isLocking, setIsLocking] = useState(false);

  // Fetch full capability details with tests
  const { data: capabilityDetails, isLoading } = useQuery<TddCapabilityWithTests>({
    queryKey: ["tdd-capability", projectId, capability?.capability_id],
    queryFn: () => fetchTddCapability(projectId, capability!.capability_id),
    enabled: open && !!capability,
  });

  const handleLock = async () => {
    if (!capability) return;
    setIsLocking(true);
    try {
      await lockTddCapability(projectId, capability.capability_id);
      queryClient.invalidateQueries({ queryKey: ["tdd-capability", projectId, capability.capability_id] });
      queryClient.invalidateQueries({ queryKey: ["tdd-capabilities", projectId] });
    } finally {
      setIsLocking(false);
    }
  };

  const details = capabilityDetails || capability;
  const tests = capabilityDetails?.tests || [];

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent className="w-full max-w-lg">
        <SheetHeader className="flex flex-row items-start justify-between gap-4">
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 mb-1">
              {details && getStatusIcon(details.status, "md")}
              <span className={`text-xs px-2 py-0.5 rounded border ${getStatusColor(details?.status || "pending")}`}>
                {details?.status.replace("_", " ")}
              </span>
              {details?.locked_at && (
                <Badge variant="amber" className="gap-1 text-xs">
                  <Lock className="h-3 w-3" />
                  Locked
                </Badge>
              )}
            </div>
            <SheetTitle className="truncate">{details?.name}</SheetTitle>
            <p className="text-xs text-slate-500 mono mt-1">{details?.capability_id}</p>
          </div>
          <SheetClose onClose={() => onOpenChange(false)} />
        </SheetHeader>

        <SheetBody className="space-y-6">
          {/* Actions */}
          {details && !details.locked_at && details.status === "passing" && (
            <Button onClick={handleLock} disabled={isLocking} className="w-full">
              {isLocking ? (
                <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-2" />
              ) : (
                <Lock className="h-4 w-4 mr-2" />
              )}
              Lock Capability
            </Button>
          )}

          {/* Description */}
          {details?.description && (
            <div>
              <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2">
                Description
              </h3>
              <p className="text-sm text-slate-300">{details.description}</p>
            </div>
          )}

          {/* Info Grid */}
          <div className="grid grid-cols-2 gap-3">
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3">
              <div className="text-xs text-slate-500 mb-1">Priority</div>
              <span className={`text-sm px-2 py-0.5 rounded border ${getPriorityColor(details?.priority || 2)}`}>
                P{details?.priority}
              </span>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3">
              <div className="text-xs text-slate-500 mb-1">Status</div>
              <span className={`text-sm px-2 py-0.5 rounded border ${getStatusColor(details?.status || "pending")}`}>
                {details?.status.replace("_", " ")}
              </span>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3">
              <div className="text-xs text-slate-500 mb-1">Created</div>
              <div className="text-sm text-slate-300">{formatDate(details?.created_at || null)}</div>
            </div>
            <div className="rounded-lg border border-slate-700 bg-slate-800/50 p-3">
              <div className="text-xs text-slate-500 mb-1">Locked</div>
              <div className="text-sm text-slate-300">
                {details?.locked_at ? formatDate(details.locked_at) : "Not locked"}
              </div>
            </div>
          </div>

          {/* Linked Tests */}
          <div>
            <h3 className="text-xs font-medium text-slate-400 uppercase tracking-wider mb-2 flex items-center gap-1.5">
              <FlaskConical className="h-3.5 w-3.5" />
              Linked Tests ({tests.length})
            </h3>
            {tests.length > 0 ? (
              <div className="space-y-2">
                {tests.map((test) => (
                  <div
                    key={test.id}
                    className="flex items-center gap-2 rounded-lg border border-slate-700 bg-slate-800/50 p-2"
                  >
                    {getTestResultIcon(test.last_result)}
                    <Badge variant="slate" className="text-xs">
                      {test.test_type}
                    </Badge>
                    <span className="flex-1 text-sm text-slate-300 truncate">{test.name}</span>
                    {test.is_primary && (
                      <Badge variant="phosphor" className="text-xs">Primary</Badge>
                    )}
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-slate-700 bg-slate-800/30 p-4 text-center text-sm text-slate-500">
                <Link2 className="h-8 w-8 mx-auto mb-2 text-slate-600" />
                No tests linked to this capability
              </div>
            )}
          </div>
        </SheetBody>
      </SheetContent>
    </Sheet>
  );
}
