"use client";

import { forwardRef, type HTMLAttributes } from "react";
import { clsx } from "clsx";

type ScrollAreaProps = HTMLAttributes<HTMLDivElement>;

export const ScrollArea = forwardRef<HTMLDivElement, ScrollAreaProps>(
  ({ className, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        className={clsx(
          "overflow-auto scrollbar-thin scrollbar-track-slate-900 scrollbar-thumb-slate-700",
          "hover:scrollbar-thumb-slate-600",
          className
        )}
        {...props}
      >
        {children}
      </div>
    );
  }
);

ScrollArea.displayName = "ScrollArea";
