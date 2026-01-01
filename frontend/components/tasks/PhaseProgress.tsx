"use client";

import { Check } from "lucide-react";

interface PhaseProgressProps {
  currentPhase: "plan" | "implement" | "test" | "verify" | "complete" | null | undefined;
}

const PHASES = [
  { id: "plan", label: "Plan" },
  { id: "implement", label: "Implement" },
  { id: "test", label: "Test" },
  { id: "verify", label: "Verify" },
  { id: "complete", label: "Complete" },
] as const;

export function PhaseProgress({ currentPhase }: PhaseProgressProps) {
  const currentIndex = currentPhase
    ? PHASES.findIndex((p) => p.id === currentPhase)
    : -1;

  return (
    <div className="flex items-center gap-1">
      {PHASES.map((phase, index) => {
        const isComplete = index < currentIndex || currentPhase === "complete";
        const isCurrent = index === currentIndex && currentPhase !== "complete";
        const isPending = index > currentIndex;

        return (
          <div key={phase.id} className="flex items-center">
            {/* Phase Indicator */}
            <div className="flex flex-col items-center">
              <div
                className={`
                  w-6 h-6 rounded-full flex items-center justify-center
                  text-2xs font-medium transition-all duration-300
                  ${
                    isComplete
                      ? "bg-phosphor-500/20 text-phosphor-400 ring-1 ring-phosphor-500/30"
                      : isCurrent
                        ? "bg-blue-500/20 text-blue-400 ring-2 ring-blue-500/50"
                        : "bg-slate-800 text-slate-600"
                  }
                `}
              >
                {isComplete ? (
                  <Check className="w-3 h-3" />
                ) : (
                  <span>{index + 1}</span>
                )}
              </div>
              <span
                className={`
                  text-2xs mt-1 transition-colors duration-300
                  ${
                    isComplete
                      ? "text-phosphor-400"
                      : isCurrent
                        ? "text-blue-400 font-medium"
                        : "text-slate-600"
                  }
                `}
              >
                {phase.label}
              </span>
            </div>

            {/* Connector Line */}
            {index < PHASES.length - 1 && (
              <div
                className={`
                  w-8 h-0.5 mx-1 transition-colors duration-300
                  ${isComplete ? "bg-phosphor-500/30" : "bg-slate-800"}
                `}
              />
            )}
          </div>
        );
      })}
    </div>
  );
}
