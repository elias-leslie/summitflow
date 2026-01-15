"use client";

import { clsx } from "clsx";
import { Zap, AlertTriangle, Infinity, Loader2 } from "lucide-react";

interface ExtractionThrottlePanelProps {
  enabled: boolean;
  rpmLimit: number;
  onEnabledChange: (enabled: boolean) => void;
  onRpmChange: (rpm: number) => void;
  disabled?: boolean;
  saving?: boolean;
}

const RPM_STOPS = [
  { value: 0, label: "Off", description: "Disabled" },
  { value: 5, label: "Minimal", description: "5/min" },
  { value: 10, label: "Low", description: "10/min" },
  { value: 15, label: "Medium", description: "15/min" },
  { value: 30, label: "High", description: "30/min" },
  { value: 60, label: "Unlimited", description: "60/min" },
] as const;

export function ExtractionThrottlePanel({
  enabled,
  rpmLimit,
  onEnabledChange,
  onRpmChange,
  disabled = false,
  saving = false,
}: ExtractionThrottlePanelProps) {
  const effectiveRpm = enabled ? rpmLimit : 0;
  const isOff = effectiveRpm === 0;
  const isUnlimited = effectiveRpm >= 60;

  const handleStopClick = (value: number) => {
    if (disabled || saving) return;

    if (value === 0) {
      onEnabledChange(false);
    } else {
      if (!enabled) onEnabledChange(true);
      onRpmChange(value);
    }
  };

  return (
    <div
      className={clsx(
        "p-6 rounded-lg border transition-colors",
        isOff
          ? "bg-red-950/20 border-red-900/50"
          : "bg-slate-800/50 border-slate-700",
        disabled && "opacity-50 pointer-events-none",
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-sm font-medium text-slate-200 flex items-center gap-2">
          <Zap
            className={clsx(
              "w-4 h-4 transition-colors",
              isOff
                ? "text-red-400"
                : isUnlimited
                  ? "text-phosphor-400"
                  : "text-amber-400",
            )}
          />
          AI Extraction Rate
          {saving && (
            <Loader2 className="w-3 h-3 animate-spin text-slate-400 ml-1" />
          )}
        </h3>

        {/* Current Value Badge */}
        <div
          className={clsx(
            "px-2.5 py-1 rounded-full text-xs font-medium flex items-center gap-1.5 transition-colors",
            isOff
              ? "bg-red-900/50 text-red-300"
              : isUnlimited
                ? "bg-phosphor-900/50 text-phosphor-300"
                : "bg-amber-900/40 text-amber-300",
          )}
        >
          {isOff ? (
            <>
              <AlertTriangle className="w-3 h-3" />
              Disabled
            </>
          ) : isUnlimited ? (
            <>
              <Infinity className="w-3 h-3" />
              Unlimited
            </>
          ) : (
            <>
              <span className="font-mono">{effectiveRpm}</span>
              <span className="text-amber-400/70">RPM</span>
            </>
          )}
        </div>
      </div>

      <p className="text-xs text-slate-400 mb-5">
        Limit AI extraction queries to control costs. Lower values force lean
        observation design.
      </p>

      {/* Segmented Control */}
      <div className="relative">
        {/* Track background */}
        <div className="absolute inset-x-0 top-1/2 -translate-y-1/2 h-1 bg-slate-700/50 rounded-full" />

        {/* Progress fill */}
        <div
          className={clsx(
            "absolute top-1/2 -translate-y-1/2 h-1 rounded-full transition-all duration-200",
            isOff
              ? "bg-red-500/50"
              : isUnlimited
                ? "bg-phosphor-500/50"
                : "bg-amber-500/50",
          )}
          style={{
            left: 0,
            width: `${(RPM_STOPS.findIndex((s) => s.value === effectiveRpm) / (RPM_STOPS.length - 1)) * 100}%`,
          }}
        />

        {/* Stops */}
        <div className="relative flex justify-between">
          {RPM_STOPS.map((stop, idx) => {
            const isActive = stop.value === effectiveRpm;
            const isPast = stop.value < effectiveRpm;

            return (
              <button
                key={stop.value}
                onClick={() => handleStopClick(stop.value)}
                disabled={disabled || saving}
                className={clsx(
                  "group flex flex-col items-center focus:outline-none",
                  "transition-all duration-150",
                  idx === 0 && "items-start",
                  idx === RPM_STOPS.length - 1 && "items-end",
                )}
              >
                {/* Dot */}
                <div
                  className={clsx(
                    "w-4 h-4 rounded-full border-2 transition-all duration-150",
                    "group-hover:scale-110",
                    isActive
                      ? stop.value === 0
                        ? "bg-red-500 border-red-400 shadow-[0_0_8px_rgba(239,68,68,0.5)]"
                        : stop.value === 60
                          ? "bg-phosphor-500 border-phosphor-400 shadow-[0_0_8px_rgba(34,197,94,0.5)]"
                          : "bg-amber-500 border-amber-400 shadow-[0_0_8px_rgba(245,158,11,0.5)]"
                      : isPast
                        ? "bg-slate-600 border-slate-500"
                        : "bg-slate-800 border-slate-600 group-hover:border-slate-500",
                  )}
                />

                {/* Label */}
                <span
                  className={clsx(
                    "mt-2 text-[10px] font-medium transition-colors",
                    isActive
                      ? stop.value === 0
                        ? "text-red-400"
                        : stop.value === 60
                          ? "text-phosphor-400"
                          : "text-amber-400"
                      : "text-slate-500 group-hover:text-slate-400",
                  )}
                >
                  {stop.label}
                </span>

                {/* Value (shown on hover/active) */}
                <span
                  className={clsx(
                    "text-[9px] transition-opacity",
                    isActive
                      ? "opacity-100 text-slate-400"
                      : "opacity-0 group-hover:opacity-100 text-slate-500",
                  )}
                >
                  {stop.description}
                </span>
              </button>
            );
          })}
        </div>
      </div>

      {/* Warning message when off */}
      {isOff && (
        <div className="mt-5 p-3 rounded-md bg-red-950/50 border border-red-900/50 flex items-start gap-2">
          <AlertTriangle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
          <p className="text-xs text-red-300/90">
            AI extraction is disabled. Observations will not be processed until
            re-enabled.
          </p>
        </div>
      )}
    </div>
  );
}
