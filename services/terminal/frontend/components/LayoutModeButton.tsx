"use client";

import { clsx } from "clsx";
import { Square, Rows2, Columns2, LucideIcon } from "lucide-react";

// Define LayoutMode locally for standalone terminal app
export type LayoutMode = "single" | "horizontal" | "vertical";

const LAYOUT_BUTTONS: { mode: LayoutMode; icon: LucideIcon; title: string }[] = [
  { mode: "single", icon: Square, title: "Single pane" },
  { mode: "horizontal", icon: Rows2, title: "Horizontal split" },
  { mode: "vertical", icon: Columns2, title: "Vertical split" },
];

interface LayoutModeButtonsProps {
  layoutMode: LayoutMode;
  onLayoutChange: (mode: LayoutMode) => void;
}

export function LayoutModeButtons({ layoutMode, onLayoutChange }: LayoutModeButtonsProps) {
  return (
    <>
      {LAYOUT_BUTTONS.map(({ mode, icon: Icon, title }) => (
        <button
          key={mode}
          onClick={() => onLayoutChange(mode)}
          title={title}
          className={clsx(
            "p-1.5 rounded transition-colors",
            layoutMode === mode
              ? "bg-slate-700 text-phosphor-400"
              : "text-slate-500 hover:text-slate-300 hover:bg-slate-700/50"
          )}
        >
          <Icon className="w-4 h-4" />
        </button>
      ))}
    </>
  );
}
