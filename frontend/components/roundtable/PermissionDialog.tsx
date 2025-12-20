"use client";

import { useState, useEffect, useRef } from "react";
import { FileEdit, FilePlus, Trash2, FolderPlus, AlertTriangle, Clock, type LucideIcon } from "lucide-react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import type { PermissionRequest } from "@/lib/api";

const TIMEOUT_SECONDS = 60;

interface PermissionDialogProps {
  open: boolean;
  request: PermissionRequest | null;
  onApprove: () => void;
  onDeny: () => void;
  isLoading: boolean;
}

const TOOL_ICONS: Record<string, LucideIcon> = {
  write_file: FilePlus,
  edit_file: FileEdit,
  delete_file: Trash2,
  create_directory: FolderPlus,
};

const TOOL_LABELS: Record<string, string> = {
  write_file: "Write File",
  edit_file: "Edit File",
  delete_file: "Delete File",
  create_directory: "Create Directory",
};

export function PermissionDialog({
  open,
  request,
  onApprove,
  onDeny,
  isLoading,
}: PermissionDialogProps) {
  const [countdown, setCountdown] = useState(TIMEOUT_SECONDS);
  const lastPermissionIdRef = useRef<string | null>(null);

  // Reset countdown when a new permission request arrives
  useEffect(() => {
    if (request?.permission_id && request.permission_id !== lastPermissionIdRef.current) {
      lastPermissionIdRef.current = request.permission_id;
      setCountdown(TIMEOUT_SECONDS);
    }
  }, [request?.permission_id]);

  // Countdown timer
  useEffect(() => {
    if (!open || !request || isLoading) return;

    const interval = setInterval(() => {
      setCountdown((prev) => {
        if (prev <= 1) {
          // Auto-deny when countdown reaches 0
          onDeny();
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(interval);
  }, [open, request, isLoading, onDeny]);

  if (!request) return null;

  const Icon = TOOL_ICONS[request.tool_name] || AlertTriangle;
  const toolLabel = TOOL_LABELS[request.tool_name] || request.tool_name;
  const filePath =
    (request.params.file_path as string) ||
    (request.params.path as string) ||
    "Unknown path";

  // Determine icon color based on tool type
  const iconColorClass =
    request.tool_name === "delete_file"
      ? "text-rose-400"
      : request.tool_name === "edit_file"
      ? "text-amber-400"
      : "text-phosphor-400";

  return (
    <Dialog open={open} onOpenChange={() => {}}>
      <DialogContent className="w-full max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className={`p-2 rounded-lg bg-slate-800 ${iconColorClass}`}>
                <Icon className="w-5 h-5" />
              </div>
              <div>
                <span className="text-white">{toolLabel}</span>
                <span className="ml-2 text-xs text-slate-400 uppercase">
                  {request.agent}
                </span>
              </div>
            </div>
            {/* Countdown timer */}
            <div
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium ${
                countdown <= 10
                  ? "bg-rose-900/30 text-rose-400 animate-pulse"
                  : countdown <= 30
                  ? "bg-amber-900/30 text-amber-400"
                  : "bg-slate-800 text-slate-400"
              }`}
            >
              <Clock className="w-3.5 h-3.5" />
              <span className="tabular-nums">{countdown}s</span>
            </div>
          </DialogTitle>
        </DialogHeader>

        <div className="px-5 py-4 space-y-4">
          {/* File path */}
          <div>
            <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">
              Target Path
            </label>
            <div className="font-mono text-sm text-slate-200 bg-slate-800 px-3 py-2 rounded border border-slate-700 break-all">
              {filePath}
            </div>
          </div>

          {/* Preview */}
          {request.preview && (
            <div>
              <label className="block text-xs font-medium text-slate-400 uppercase tracking-wider mb-1">
                Preview
              </label>
              <pre className="font-mono text-xs text-slate-300 bg-slate-800 px-3 py-2 rounded border border-slate-700 overflow-auto max-h-48 whitespace-pre-wrap">
                {request.preview}
              </pre>
            </div>
          )}

          {/* Warning for destructive actions */}
          {request.tool_name === "delete_file" && (
            <div className="flex items-start gap-2 p-3 rounded bg-rose-900/20 border border-rose-800/50 text-rose-300 text-sm">
              <AlertTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
              <span>This action cannot be undone.</span>
            </div>
          )}
        </div>

        {/* Actions */}
        <div className="flex justify-end gap-3 px-5 py-4 border-t border-slate-700">
          <Button
            variant="secondary"
            onClick={onDeny}
            disabled={isLoading}
          >
            Deny
          </Button>
          <Button
            variant={request.tool_name === "delete_file" ? "destructive" : "primary"}
            onClick={onApprove}
            disabled={isLoading}
          >
            {isLoading ? "Processing..." : "Approve"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
