"use client";

import { useCallback, useState, useRef, useEffect } from "react";
import { ChevronUp, ChevronDown, ChevronsUp, ChevronsDown, Copy, ClipboardPaste } from "lucide-react";

interface MobileScrollControlsProps {
  onScrollUp: () => void;
  onScrollDown: () => void;
  onPageUp: () => void;
  onPageDown: () => void;
  onCopy: () => Promise<string | null>;
  onPaste: (text: string) => void;
}

export function MobileScrollControls({
  onScrollUp,
  onScrollDown,
  onPageUp,
  onPageDown,
  onCopy,
  onPaste,
}: MobileScrollControlsProps) {
  const [copied, setCopied] = useState(false);
  const scrollIntervalRef = useRef<NodeJS.Timeout | null>(null);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      if (scrollIntervalRef.current) {
        clearInterval(scrollIntervalRef.current);
      }
    };
  }, []);

  // Start continuous scrolling on touch hold
  const startScrolling = useCallback((scrollFn: () => void) => {
    scrollFn(); // Immediate first scroll
    scrollIntervalRef.current = setInterval(scrollFn, 80);
  }, []);

  const stopScrolling = useCallback(() => {
    if (scrollIntervalRef.current) {
      clearInterval(scrollIntervalRef.current);
      scrollIntervalRef.current = null;
    }
  }, []);

  const handleCopy = useCallback(async () => {
    const text = await onCopy();
    if (text) {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }
  }, [onCopy]);

  const handlePaste = useCallback(async () => {
    try {
      const text = await navigator.clipboard.readText();
      if (text) {
        onPaste(text);
      }
    } catch (err) {
      console.error("Failed to paste:", err);
    }
  }, [onPaste]);

  const buttonClass = `
    w-10 h-10 flex items-center justify-center
    bg-slate-800/90 hover:bg-slate-700 active:bg-slate-600
    border border-slate-600/50 rounded-lg
    text-slate-300 active:text-white
    transition-colors touch-none select-none
  `;

  return (
    <div className="absolute right-2 top-1/2 -translate-y-1/2 flex flex-col gap-1.5 z-50">
      {/* Page Up */}
      <button
        className={buttonClass}
        onTouchStart={() => onPageUp()}
        onClick={onPageUp}
        aria-label="Page up"
      >
        <ChevronsUp size={20} />
      </button>

      {/* Scroll Up - hold to repeat */}
      <button
        className={buttonClass}
        onTouchStart={() => startScrolling(onScrollUp)}
        onTouchEnd={stopScrolling}
        onTouchCancel={stopScrolling}
        onClick={onScrollUp}
        aria-label="Scroll up"
      >
        <ChevronUp size={20} />
      </button>

      {/* Scroll Down - hold to repeat */}
      <button
        className={buttonClass}
        onTouchStart={() => startScrolling(onScrollDown)}
        onTouchEnd={stopScrolling}
        onTouchCancel={stopScrolling}
        onClick={onScrollDown}
        aria-label="Scroll down"
      >
        <ChevronDown size={20} />
      </button>

      {/* Page Down */}
      <button
        className={buttonClass}
        onTouchStart={() => onPageDown()}
        onClick={onPageDown}
        aria-label="Page down"
      >
        <ChevronsDown size={20} />
      </button>

      {/* Divider */}
      <div className="h-px bg-slate-600/50 my-1" />

      {/* Copy */}
      <button
        className={`${buttonClass} ${copied ? "bg-green-700 text-white" : ""}`}
        onClick={handleCopy}
        aria-label="Copy selected text"
      >
        <Copy size={18} />
      </button>

      {/* Paste */}
      <button
        className={buttonClass}
        onClick={handlePaste}
        aria-label="Paste from clipboard"
      >
        <ClipboardPaste size={18} />
      </button>
    </div>
  );
}
