"use client";

import { clsx } from "clsx";
import { Bot, Sparkles, Users } from "lucide-react";

export type AgentMode = "claude" | "gemini" | "both";

interface AgentModeSelectorProps {
  value: AgentMode;
  onChange: (mode: AgentMode) => void;
  disabled?: boolean;
  className?: string;
}

const modes: { value: AgentMode; icon: typeof Bot; label: string; color: string }[] = [
  { value: "claude", icon: Bot, label: "Claude", color: "text-orange-500 bg-orange-500/10 border-orange-500/30" },
  { value: "both", icon: Users, label: "Both", color: "text-purple-500 bg-purple-500/10 border-purple-500/30" },
  { value: "gemini", icon: Sparkles, label: "Gemini", color: "text-blue-500 bg-blue-500/10 border-blue-500/30" },
];

export function AgentModeSelector({
  value,
  onChange,
  disabled = false,
  className,
}: AgentModeSelectorProps) {
  return (
    <div
      className={clsx(
        "inline-flex items-center gap-0.5 p-0.5 rounded-lg bg-muted/50 border border-border",
        disabled && "opacity-50 pointer-events-none",
        className
      )}
    >
      {modes.map((mode) => {
        const Icon = mode.icon;
        const isActive = value === mode.value;

        return (
          <button
            key={mode.value}
            onClick={() => onChange(mode.value)}
            disabled={disabled}
            title={mode.label}
            className={clsx(
              "flex items-center gap-1.5 px-2 py-1 rounded-md text-xs font-medium transition-all",
              isActive
                ? clsx("border", mode.color)
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
          >
            <Icon className="h-3.5 w-3.5" />
            <span className={clsx(isActive ? "block" : "hidden sm:block")}>
              {mode.label}
            </span>
          </button>
        );
      })}
    </div>
  );
}
