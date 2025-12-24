"use client";

import { forwardRef, type TextareaHTMLAttributes } from "react";
import { clsx } from "clsx";

type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement>;

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, ...props }, ref) => {
    return (
      <textarea
        ref={ref}
        className={clsx(
          "w-full px-3 py-2 rounded-md mono text-sm",
          "bg-slate-900 border border-slate-700",
          "text-slate-200 placeholder-slate-600",
          "focus:outline-none focus:border-phosphor-500/50 focus:ring-1 focus:ring-phosphor-500/20",
          "transition-all duration-200",
          "resize-none",
          className
        )}
        {...props}
      />
    );
  }
);

Textarea.displayName = "Textarea";
