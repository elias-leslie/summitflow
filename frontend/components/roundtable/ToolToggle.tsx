"use client";

import { clsx } from "clsx";
import { Switch } from "../ui/switch";
import { LucideIcon } from "lucide-react";

export interface ToolToggleProps {
  id: string;
  label: string;
  checked: boolean;
  color: string; // Tailwind color class e.g., "phosphor-400", "amber-400", "rose-400"
  icon?: LucideIcon;
  disabled?: boolean;
  onChange: (checked: boolean) => void;
  title?: string;
}

/**
 * Reusable toggle component for tool settings in RoundtableChat.
 * Displays a label with optional icon and a switch.
 */
export function ToolToggle({
  id,
  label,
  checked,
  color,
  icon: Icon,
  disabled = false,
  onChange,
  title,
}: ToolToggleProps) {
  return (
    <div className="flex items-center gap-1.5">
      <label
        htmlFor={id}
        className={clsx(
          "flex items-center gap-1 text-xs cursor-pointer",
          checked ? `text-${color}` : "text-slate-500"
        )}
        title={title}
      >
        {Icon && <Icon className="w-3.5 h-3.5" />}
        <span>{label}</span>
      </label>
      <Switch
        id={id}
        checked={checked}
        onCheckedChange={onChange}
        disabled={disabled}
      />
    </div>
  );
}
