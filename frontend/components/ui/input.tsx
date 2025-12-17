"use client";

import { forwardRef, type InputHTMLAttributes } from "react";
import { clsx } from "clsx";

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {}

export const Input = forwardRef<HTMLInputElement, InputProps>(
  ({ className, type, ...props }, ref) => {
    return (
      <input
        type={type}
        ref={ref}
        className={clsx(
          "w-full h-10 px-3 py-2 rounded-md text-sm",
          "bg-slate-900 border border-slate-700",
          "text-slate-200 placeholder-slate-600",
          "focus:outline-none focus:border-phosphor-500/50 focus:ring-1 focus:ring-phosphor-500/20",
          "transition-all duration-200",
          "disabled:opacity-50 disabled:cursor-not-allowed",
          className
        )}
        {...props}
      />
    );
  }
);

Input.displayName = "Input";
