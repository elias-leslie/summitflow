"use client";

import { createContext, useContext, useState, useRef, type ReactNode } from "react";
import { clsx } from "clsx";

interface TooltipContextValue {
  open: boolean;
  setOpen: (open: boolean) => void;
}

const TooltipContext = createContext<TooltipContextValue | null>(null);

function useTooltip() {
  const ctx = useContext(TooltipContext);
  if (!ctx) throw new Error("Tooltip components must be used within Tooltip");
  return ctx;
}

export function TooltipProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

interface TooltipProps {
  children: ReactNode;
  delayDuration?: number;
}

export function Tooltip({ children }: TooltipProps) {
  const [open, setOpen] = useState(false);

  return (
    <TooltipContext.Provider value={{ open, setOpen }}>
      <div className="relative inline-flex">
        {children}
      </div>
    </TooltipContext.Provider>
  );
}

interface TooltipTriggerProps {
  children: ReactNode;
  asChild?: boolean;
}

export function TooltipTrigger({ children, asChild }: TooltipTriggerProps) {
  const { setOpen } = useTooltip();

  const handleMouseEnter = () => setOpen(true);
  const handleMouseLeave = () => setOpen(false);

  if (asChild) {
    // Clone children and add event handlers
    return (
      <span
        onMouseEnter={handleMouseEnter}
        onMouseLeave={handleMouseLeave}
        onFocus={handleMouseEnter}
        onBlur={handleMouseLeave}
      >
        {children}
      </span>
    );
  }

  return (
    <span
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      onFocus={handleMouseEnter}
      onBlur={handleMouseLeave}
    >
      {children}
    </span>
  );
}

interface TooltipContentProps {
  children: ReactNode;
  className?: string;
  side?: "top" | "bottom" | "left" | "right";
  sideOffset?: number;
}

export function TooltipContent({ children, className, side = "top" }: TooltipContentProps) {
  const { open } = useTooltip();

  if (!open) return null;

  const sideClasses = {
    top: "bottom-full left-1/2 -translate-x-1/2 mb-2",
    bottom: "top-full left-1/2 -translate-x-1/2 mt-2",
    left: "right-full top-1/2 -translate-y-1/2 mr-2",
    right: "left-full top-1/2 -translate-y-1/2 ml-2",
  };

  return (
    <div
      role="tooltip"
      className={clsx(
        "absolute z-50 px-2 py-1.5 text-xs rounded bg-slate-950 border border-slate-700",
        "text-slate-200 shadow-lg shadow-black/30",
        "animate-fade-in whitespace-nowrap",
        sideClasses[side],
        className
      )}
    >
      {children}
    </div>
  );
}
