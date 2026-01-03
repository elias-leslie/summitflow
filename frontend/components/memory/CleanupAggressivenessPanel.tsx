"use client";

import { useState, useEffect } from "react";
import { clsx } from "clsx";
import { Trash2, AlertTriangle, Shield, Loader2, Clock } from "lucide-react";
import {
  getCleanupSettings,
  updateCleanupSettings,
  type CleanupSettings,
} from "@/lib/api";

const CLEANUP_STOPS = [
  { level: 0, label: "Manual", description: "No auto-cleanup", icon: Shield },
  { level: 1, label: "Conservative", description: "30 days", icon: Clock },
  { level: 2, label: "Moderate", description: "14 days", icon: Clock },
  { level: 3, label: "Aggressive", description: "7 days", icon: Trash2 },
] as const;

export function CleanupAggressivenessPanel() {
  const [settings, setSettings] = useState<CleanupSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    const fetchSettings = async () => {
      try {
        const data = await getCleanupSettings();
        setSettings(data);
      } catch (error) {
        console.error("Failed to fetch cleanup settings:", error);
      } finally {
        setLoading(false);
      }
    };
    fetchSettings();
  }, []);

  const handleStopClick = async (level: number) => {
    if (saving || !settings) return;

    setSaving(true);
    try {
      const updated = await updateCleanupSettings({ level });
      setSettings(updated);
    } catch (error) {
      console.error("Failed to update cleanup settings:", error);
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="p-6 bg-slate-800/50 rounded-lg border border-slate-700 flex items-center justify-center">
        <Loader2 className="w-5 h-5 animate-spin text-slate-400" />
      </div>
    );
  }

  if (!settings) {
    return null;
  }

  const currentLevel = settings.level;
  const isManual = currentLevel === 0;
  const isAggressive = currentLevel === 3;

  return (
    <div
      className={clsx(
        "p-6 rounded-lg border transition-colors",
        isAggressive
          ? "bg-rose-950/20 border-rose-900/50"
          : isManual
          ? "bg-slate-800/50 border-slate-600"
          : "bg-slate-800/50 border-slate-700"
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
          <Trash2
            className={clsx(
              "w-4 h-4 transition-colors",
              isAggressive ? "text-rose-400" : isManual ? "text-slate-400" : "text-amber-400"
            )}
          />
          Pattern Cleanup Aggressiveness
          {saving && <Loader2 className="w-3 h-3 animate-spin text-slate-400 ml-1" />}
        </h3>

        {/* Current Value Badge */}
        <div
          className={clsx(
            "px-2.5 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 transition-colors",
            isAggressive
              ? "bg-rose-900/50 text-rose-300"
              : isManual
              ? "bg-slate-700/50 text-slate-300"
              : "bg-amber-900/40 text-amber-300"
          )}
        >
          {settings.label}
          {!isManual && (
            <span className="text-[10px] opacity-70">
              ({settings.min_age_days}d)
            </span>
          )}
        </div>
      </div>

      <p className="text-xs text-slate-400 mb-5">
        Controls how aggressively unused patterns are cleaned up. Higher = more aggressive pruning.
      </p>

      {/* Current Thresholds */}
      <div className="flex items-center gap-4 mb-5 text-xs">
        <div className="flex items-center gap-1.5 text-slate-400">
          <Clock className="w-3.5 h-3.5" />
          <span>Min Age: <span className="font-mono text-slate-300">{settings.min_age_days}</span> days</span>
        </div>
        <div className="flex items-center gap-1.5 text-slate-400">
          <span>Min Relevance: <span className="font-mono text-slate-300">{(settings.min_relevance * 100).toFixed(0)}%</span></span>
        </div>
      </div>

      {/* Segmented Control */}
      <div className="relative">
        {/* Track background */}
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 bg-slate-700/50 rounded-full" />

        {/* Progress fill */}
        <div
          className={clsx(
            "absolute top-1/2 -translate-y-1/2 h-1 rounded-full transition-all duration-200",
            isAggressive ? "bg-rose-500/50" : isManual ? "bg-slate-600/50" : "bg-amber-500/50"
          )}
          style={{
            left: 0,
            width: `${(currentLevel / (CLEANUP_STOPS.length - 1)) * 100}%`,
          }}
        />

        {/* Stops */}
        <div className="relative flex justify-between">
          {CLEANUP_STOPS.map((stop, idx) => {
            const isActive = stop.level === currentLevel;
            const isPast = stop.level < currentLevel;

            return (
              <button
                key={stop.level}
                onClick={() => handleStopClick(stop.level)}
                disabled={saving}
                className={clsx(
                  "group flex flex-col items-center focus:outline-none",
                  "transition-all duration-150",
                  idx === 0 && "items-start",
                  idx === CLEANUP_STOPS.length - 1 && "items-end"
                )}
              >
                {/* Dot */}
                <div
                  className={clsx(
                    "w-4 h-4 rounded-full border-2 transition-all duration-150",
                    "group-hover:scale-110",
                    isActive
                      ? stop.level === 0
                        ? "bg-slate-500 border-slate-400 shadow-[0_0_8px_rgba(148,163,184,0.5)]"
                        : stop.level === 3
                        ? "bg-rose-500 border-rose-400 shadow-[0_0_8px_rgba(244,63,94,0.5)]"
                        : "bg-amber-500 border-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.5)]"
                      : isPast
                      ? "bg-slate-600 border-slate-500"
                      : "bg-slate-800 border-slate-600 group-hover:border-slate-500"
                  )}
                />

                {/* Label */}
                <span
                  className={clsx(
                    "mt-2 text-[10px] font-medium transition-colors",
                    isActive
                      ? stop.level === 0
                        ? "text-slate-400"
                        : stop.level === 3
                        ? "text-rose-400"
                        : "text-amber-400"
                      : "text-slate-500 group-hover:text-slate-400"
                  )}
                >
                  {stop.label}
                </span>

                {/* Value (shown on hover/active) */}
                <span
                  className={clsx(
                    "text-[9px] transition-opacity",
                    isActive ? "opacity-100 text-slate-400" : "opacity-0 group-hover:opacity-100 text-slate-500"
                  )}
                >
                  {stop.description}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Warning message when aggressive */}
      {isAggressive && (
        <div className="mt-5 p-3 rounded-md bg-rose-950/50 border border-rose-900/50 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-rose-400 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-rose-300/90">
            Aggressive mode: Patterns unused for 7+ days with low relevance will be auto-cleaned.
          </p>
        </div>
      )}

      {/* Info message when manual */}
      {isManual && (
        <div className="mt-5 p-3 rounded-md bg-slate-800/50 border border-slate-600/50 flex items-start gap-2">
          <Shield className="w-4 h-4 text-slate-400 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-slate-400">
            Manual mode: Patterns will only be cleaned via explicit /memory_optimize runs.
          </p>
        </div>
      )}
    </div>
  );
}
