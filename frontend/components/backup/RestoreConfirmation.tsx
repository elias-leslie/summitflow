"use client";

import { useState } from "react";
import {
  AlertTriangle,
  ArrowRight,
  CheckCircle2,
  Database,
  HardDrive,
  Loader2,
  RotateCcw,
  XCircle,
} from "lucide-react";
import { clsx } from "clsx";
import { restoreBackup, type Backup } from "@/lib/api/backups";

type RestoreStep = "preview" | "confirm" | "restoring" | "success" | "error";

interface RestoreConfirmationProps {
  backup: Backup;
  projectId: string;
  projectName: string;
  onClose: () => void;
  onSuccess?: () => void;
}

function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes === 0) return "-";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let size = bytes;
  while (size >= 1024 && i < units.length - 1) {
    size /= 1024;
    i++;
  }
  return `${size.toFixed(1)} ${units[i]}`;
}

function formatDate(dateStr: string | null): string {
  if (!dateStr) return "-";
  const date = new Date(dateStr);
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function RestoreConfirmation({
  backup,
  projectId,
  projectName,
  onClose,
  onSuccess,
}: RestoreConfirmationProps) {
  const [step, setStep] = useState<RestoreStep>("preview");
  const [confirmText, setConfirmText] = useState("");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  const isConfirmValid = confirmText === projectName;

  const handleRestore = async () => {
    setStep("restoring");
    setErrorMessage(null);

    try {
      await restoreBackup(projectId, backup.id);
      setStep("success");
      onSuccess?.();
    } catch (err) {
      setStep("error");
      setErrorMessage(
        err instanceof Error
          ? err.message
          : "Restore failed. Please try again.",
      );
    }
  };

  // Step indicators
  const StepIndicator = ({
    stepNum,
    label,
    active,
    completed,
  }: {
    stepNum: number;
    label: string;
    active: boolean;
    completed: boolean;
  }) => (
    <div className="flex items-center gap-2">
      <div
        className={clsx(
          "w-6 h-6 rounded-full flex items-center justify-center text-xs font-medium",
          completed
            ? "bg-green-500 text-white"
            : active
              ? "bg-phosphor-500 text-white"
              : "bg-slate-700 text-slate-400",
        )}
      >
        {completed ? <CheckCircle2 className="w-4 h-4" /> : stepNum}
      </div>
      <span
        className={clsx(
          "text-sm",
          active ? "text-slate-200" : "text-slate-500",
        )}
      >
        {label}
      </span>
    </div>
  );

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-800 rounded-lg border border-slate-700 w-full max-w-lg">
        {/* Header */}
        <div className="px-6 py-4 border-b border-slate-700">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-yellow-500/20 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-yellow-400" />
            </div>
            <div>
              <h2 className="text-lg font-semibold text-slate-100">
                Restore Backup
              </h2>
              <p className="text-sm text-slate-400">
                This will overwrite current data
              </p>
            </div>
          </div>

          {/* Progress Steps */}
          {(step === "preview" || step === "confirm") && (
            <div className="flex items-center gap-4 mt-4">
              <StepIndicator
                stepNum={1}
                label="Preview"
                active={step === "preview"}
                completed={step === "confirm"}
              />
              <ArrowRight className="w-4 h-4 text-slate-600" />
              <StepIndicator
                stepNum={2}
                label="Confirm"
                active={step === "confirm"}
                completed={false}
              />
            </div>
          )}
        </div>

        {/* Content */}
        <div className="p-6">
          {/* Step 1: Preview */}
          {step === "preview" && (
            <div className="space-y-4">
              <div className="p-4 bg-slate-700/50 rounded-lg space-y-3">
                <h3 className="text-sm font-medium text-slate-300 mb-3">
                  What will be restored:
                </h3>
                <div className="flex items-center gap-3 text-sm">
                  <Database className="w-4 h-4 text-blue-400" />
                  <span className="text-slate-300">Database</span>
                  <span className="text-slate-500">
                    ({formatBytes(backup.db_size_bytes)})
                  </span>
                </div>
                <div className="flex items-center gap-3 text-sm">
                  <HardDrive className="w-4 h-4 text-purple-400" />
                  <span className="text-slate-300">Project Files</span>
                  <span className="text-slate-500">
                    ({formatBytes(backup.files_size_bytes)})
                  </span>
                </div>
              </div>

              <div className="p-4 bg-slate-700/50 rounded-lg">
                <div className="text-sm space-y-2">
                  <div className="flex justify-between">
                    <span className="text-slate-400">Backup ID</span>
                    <span className="font-mono text-slate-200">
                      {backup.id}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Created</span>
                    <span className="text-slate-200">
                      {formatDate(backup.created_at)}
                    </span>
                  </div>
                  <div className="flex justify-between">
                    <span className="text-slate-400">Total Size</span>
                    <span className="text-slate-200">
                      {formatBytes(backup.size_bytes)}
                    </span>
                  </div>
                  {backup.note && (
                    <div className="flex justify-between">
                      <span className="text-slate-400">Note</span>
                      <span className="text-slate-200">{backup.note}</span>
                    </div>
                  )}
                </div>
              </div>

              <div className="p-3 bg-yellow-500/10 border border-yellow-500/30 rounded-lg">
                <p className="text-sm text-yellow-300">
                  <strong>Warning:</strong> Restoring will overwrite your
                  current database and project files. This action cannot be
                  undone.
                </p>
              </div>
            </div>
          )}

          {/* Step 2: Confirm with project name */}
          {step === "confirm" && (
            <div className="space-y-4">
              <div className="p-4 bg-red-500/10 border border-red-500/30 rounded-lg">
                <p className="text-sm text-red-300">
                  <strong>Final Confirmation Required</strong>
                  <br />
                  To proceed, type the project name below:
                </p>
                <p className="mt-2 text-lg font-mono text-red-400 text-center">
                  {projectName}
                </p>
              </div>

              <div>
                <label
                  htmlFor="confirm-project-name"
                  className="block text-sm font-medium text-slate-300 mb-2"
                >
                  Type project name to confirm
                </label>
                <input
                  id="confirm-project-name"
                  type="text"
                  value={confirmText}
                  onChange={(e) => setConfirmText(e.target.value)}
                  placeholder={projectName}
                  className={clsx(
                    "w-full px-3 py-2 bg-slate-700 border rounded-md text-slate-200",
                    "placeholder-slate-500 focus:outline-none focus:ring-2",
                    isConfirmValid
                      ? "border-green-500 focus:ring-green-500"
                      : "border-slate-600 focus:ring-phosphor-500",
                  )}
                  autoComplete="off"
                  autoFocus
                />
                {confirmText && !isConfirmValid && (
                  <p className="mt-1 text-xs text-red-400">
                    Text does not match project name
                  </p>
                )}
              </div>
            </div>
          )}

          {/* Restoring state */}
          {step === "restoring" && (
            <div className="py-8 text-center">
              <Loader2 className="w-12 h-12 text-phosphor-400 animate-spin mx-auto mb-4" />
              <h3 className="text-lg font-medium text-slate-200 mb-2">
                Restoring...
              </h3>
              <p className="text-sm text-slate-400">
                Please wait while your data is being restored.
                <br />
                This may take several minutes.
              </p>
            </div>
          )}

          {/* Success state */}
          {step === "success" && (
            <div className="py-8 text-center">
              <div className="w-16 h-16 bg-green-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                <CheckCircle2 className="w-8 h-8 text-green-400" />
              </div>
              <h3 className="text-lg font-medium text-slate-200 mb-2">
                Restore Started
              </h3>
              <p className="text-sm text-slate-400">
                The restore process has been queued.
                <br />
                Your data will be restored shortly.
              </p>
            </div>
          )}

          {/* Error state */}
          {step === "error" && (
            <div className="py-8 text-center">
              <div className="w-16 h-16 bg-red-500/20 rounded-full flex items-center justify-center mx-auto mb-4">
                <XCircle className="w-8 h-8 text-red-400" />
              </div>
              <h3 className="text-lg font-medium text-slate-200 mb-2">
                Restore Failed
              </h3>
              <p className="text-sm text-red-400">{errorMessage}</p>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="px-6 py-4 border-t border-slate-700 flex justify-between">
          {step === "preview" && (
            <>
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
              >
                Cancel
              </button>
              <button
                onClick={() => setStep("confirm")}
                className="flex items-center gap-2 px-4 py-2 text-sm bg-yellow-600 text-white
                           hover:bg-yellow-500 rounded-md transition-colors font-medium"
              >
                Continue
                <ArrowRight className="w-4 h-4" />
              </button>
            </>
          )}

          {step === "confirm" && (
            <>
              <button
                onClick={() => {
                  setStep("preview");
                  setConfirmText("");
                }}
                className="px-4 py-2 text-sm text-slate-400 hover:text-slate-200 transition-colors"
              >
                Back
              </button>
              <button
                onClick={handleRestore}
                disabled={!isConfirmValid}
                className={clsx(
                  "flex items-center gap-2 px-4 py-2 text-sm rounded-md transition-colors font-medium",
                  isConfirmValid
                    ? "bg-red-600 text-white hover:bg-red-500"
                    : "bg-slate-700 text-slate-500 cursor-not-allowed",
                )}
              >
                <RotateCcw className="w-4 h-4" />
                Restore Backup
              </button>
            </>
          )}

          {step === "restoring" && (
            <div className="w-full text-center">
              <span className="text-sm text-slate-500">Please wait...</span>
            </div>
          )}

          {(step === "success" || step === "error") && (
            <div className="w-full flex justify-end">
              <button
                onClick={onClose}
                className="px-4 py-2 text-sm bg-slate-700 text-slate-200
                           hover:bg-slate-600 rounded-md transition-colors font-medium"
              >
                Close
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
