"use client";

import { forwardRef, type LabelHTMLAttributes } from "react";
import { clsx } from "clsx";

interface LabelProps extends LabelHTMLAttributes<HTMLLabelElement> {}

export const Label = forwardRef<HTMLLabelElement, LabelProps>(
  ({ className, ...props }, ref) => {
    return (
      <label
        ref={ref}
        className={clsx(
          "text-sm font-medium text-slate-300",
          "cursor-pointer",
          className
        )}
        {...props}
      />
    );
  }
);

Label.displayName = "Label";
