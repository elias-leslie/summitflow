"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Clock,
  Layers,
  Zap,
  CheckCircle2,
  XCircle,
} from "lucide-react";
import { clsx } from "clsx";
import { Slider } from "../ui/slider";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import {
  getAutonomousSettings,
  updateAutonomousSettings,
  type AutonomousExecutionSettingsUpdate,
} from "@/lib/api";

interface AutonomousSettingsPanelProps {
  projectId: string;
}

function formatHour(hour: number): string {
  if (hour === 0) return "12 AM";
  if (hour === 12) return "12 PM";
  if (hour === 24) return "12 AM";
  if (hour < 12) return `${hour} AM`;
  return `${hour - 12} PM`;
}

function isInTimeWindow(startHour: number, endHour: number): boolean {
  const now = new Date();
  const currentHour = now.getHours();

  // Handle 24/7 case
  if (startHour === 0 && endHour === 24) return true;

  // Handle same-day window (e.g., 9am - 6pm)
  if (startHour < endHour) {
    return currentHour >= startHour && currentHour < endHour;
  }

  // Handle overnight window (e.g., 10pm - 6am)
  return currentHour >= startHour || currentHour < endHour;
}

export function AutonomousSettingsPanel({
  projectId,
}: AutonomousSettingsPanelProps) {
  const queryClient = useQueryClient();
  const [currentInWindow, setCurrentInWindow] = useState(false);

  const { data: settings, isLoading } = useQuery({
    queryKey: ["autonomous-settings", projectId],
    queryFn: () => getAutonomousSettings(projectId),
  });

  // Update time window status every minute
  useEffect(() => {
    if (!settings) return;

    const updateStatus = () => {
      setCurrentInWindow(
        isInTimeWindow(settings.start_hour, settings.end_hour),
      );
    };

    updateStatus();
    const interval = setInterval(updateStatus, 60000); // Check every minute

    return () => clearInterval(interval);
  }, [settings]);

  const mutation = useMutation({
    mutationFn: (update: AutonomousExecutionSettingsUpdate) =>
      updateAutonomousSettings(projectId, update),
    onSuccess: () => {
      queryClient.invalidateQueries({
        queryKey: ["autonomous-settings", projectId],
      });
    },
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!settings) {
    return (
      <div className="text-sm text-slate-400 py-4">
        Failed to load autonomous settings
      </div>
    );
  }

  const handleTimeRangeChange = (values: number[]) => {
    const [start, end] = values;
    mutation.mutate({ start_hour: start, end_hour: end });
  };

  const handleConcurrencyChange = (value: string) => {
    mutation.mutate({ max_concurrent: parseInt(value, 10) });
  };

  const handleEnabledToggle = () => {
    mutation.mutate({ enabled: !settings.enabled });
  };

  return (
    <div className="space-y-6">
      {/* Master Toggle */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <div className="flex items-center justify-between">
          <div>
            <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
              <Zap className="w-4 h-4 text-yellow-400" />
              Autonomous Execution
            </h3>
            <p className="text-xs text-slate-400 mt-1">
              Enable AI agents to automatically execute refactor, debt, and
              regression tasks
            </p>
          </div>
          <button
            onClick={handleEnabledToggle}
            disabled={mutation.isPending}
            className={clsx(
              "relative w-12 h-6 rounded-full transition-colors",
              settings.enabled ? "bg-phosphor-500" : "bg-slate-600",
            )}
          >
            <span
              className={clsx(
                "absolute top-1 w-4 h-4 bg-white rounded-full transition-transform",
                settings.enabled ? "translate-x-7" : "translate-x-1",
              )}
            />
          </button>
        </div>
      </div>

      {/* Time Range */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
            <Clock className="w-4 h-4 text-slate-400" />
            Execution Window
          </h3>
          {/* Current window status indicator */}
          {settings.enabled && (
            <span
              className={clsx(
                "flex items-center gap-1 text-xs px-2 py-1 rounded-full",
                currentInWindow
                  ? "bg-phosphor-500/20 text-phosphor-400"
                  : "bg-amber-500/20 text-amber-400",
              )}
            >
              {currentInWindow ? (
                <>
                  <CheckCircle2 className="w-3 h-3" />
                  Active window
                </>
              ) : (
                <>
                  <XCircle className="w-3 h-3" />
                  Outside window
                </>
              )}
            </span>
          )}
        </div>
        <p className="text-xs text-slate-400 mb-6">
          Set the daily time range when autonomous execution is allowed
        </p>

        <div className="space-y-4">
          <div className="flex items-center justify-between text-sm text-slate-300">
            <span>{formatHour(settings.start_hour)}</span>
            <span className="text-slate-500">to</span>
            <span>{formatHour(settings.end_hour)}</span>
          </div>

          <Slider
            value={[settings.start_hour, settings.end_hour]}
            min={0}
            max={24}
            step={1}
            onValueChange={handleTimeRangeChange}
            disabled={mutation.isPending}
            className="w-full"
          />

          <div className="flex justify-between text-xs text-slate-500">
            <span>12 AM</span>
            <span>6 AM</span>
            <span>12 PM</span>
            <span>6 PM</span>
            <span>12 AM</span>
          </div>
        </div>

        {settings.start_hour === 0 && settings.end_hour === 24 && (
          <p className="text-xs text-phosphor-400 mt-3">
            Execution allowed 24/7
          </p>
        )}
      </div>

      {/* Concurrency */}
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700">
        <h3 className="text-sm font-medium text-slate-200 mb-2 flex items-center gap-2">
          <Layers className="w-4 h-4 text-slate-400" />
          Max Concurrent Tasks
        </h3>
        <p className="text-xs text-slate-400 mb-4">
          Maximum number of tasks to execute in parallel
        </p>

        <Select
          value={settings.max_concurrent.toString()}
          onValueChange={handleConcurrencyChange}
          disabled={mutation.isPending}
        >
          <SelectTrigger className="w-full max-w-[200px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="1">1 task (conservative)</SelectItem>
            <SelectItem value="2">2 tasks (balanced)</SelectItem>
            <SelectItem value="3">3 tasks (aggressive)</SelectItem>
          </SelectContent>
        </Select>

        <p className="text-xs text-slate-500 mt-3">
          Higher concurrency uses more resources but completes work faster
        </p>
      </div>

      {/* Save indicator */}
      {mutation.isPending && (
        <div className="flex items-center justify-center gap-2 text-sm text-slate-400">
          <Loader2 className="w-4 h-4 animate-spin" />
          Saving...
        </div>
      )}
    </div>
  );
}
