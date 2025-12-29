"use client";

import { useEffect, useRef, useState, useCallback, forwardRef, useImperativeHandle } from "react";
import { clsx } from "clsx";

// Dynamic imports for xterm (client-side only)
let Terminal: typeof import("@xterm/xterm").Terminal;
let FitAddon: typeof import("@xterm/addon-fit").FitAddon;
let WebLinksAddon: typeof import("@xterm/addon-web-links").WebLinksAddon;
let ClipboardAddon: typeof import("@xterm/addon-clipboard").ClipboardAddon;

interface TerminalProps {
  sessionId: string;
  workingDir?: string;
  className?: string;
  onDisconnect?: () => void;
  onStatusChange?: (status: ConnectionStatus) => void;
  fontFamily?: string;
  fontSize?: number;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error" | "session_dead" | "timeout";

export interface TerminalHandle {
  reconnect: () => void;
  getContent: () => string;
  sendInput: (data: string) => void;
  status: ConnectionStatus;
}

// Check if we're on a mobile device (used for pull-to-refresh prevention)
function isMobileDevice(): boolean {
  if (typeof window === "undefined") return false;
  return /Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(
    navigator.userAgent
  ) || window.innerWidth < 768;
}

export const TerminalComponent = forwardRef<TerminalHandle, TerminalProps>(function TerminalComponent({
  sessionId,
  workingDir,
  className,
  onDisconnect,
  onStatusChange,
  fontFamily = "'JetBrains Mono', monospace",
  fontSize = 14,
}, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<InstanceType<typeof Terminal> | null>(null);
  const fitAddonRef = useRef<InstanceType<typeof FitAddon> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const connectWebSocketRef = useRef<(() => void) | null>(null);

  // Store callback in ref to avoid re-render loops
  const onStatusChangeRef = useRef(onStatusChange);
  useEffect(() => {
    onStatusChangeRef.current = onStatusChange;
  }, [onStatusChange]);

  // Notify parent of status changes (uses ref to avoid dependency on callback)
  useEffect(() => {
    onStatusChangeRef.current?.(status);
  }, [status]);

  // Expose functions to parent
  useImperativeHandle(ref, () => ({
    reconnect: () => {
      if (connectWebSocketRef.current) {
        // Close existing connection if any
        if (wsRef.current) {
          wsRef.current.close();
        }
        terminalRef.current?.writeln("\x1b[33mReconnecting...\x1b[0m");
        setStatus("connecting");
        connectWebSocketRef.current();
      }
    },
    getContent: () => {
      if (!terminalRef.current) return "";
      // Select all text and get the selection
      terminalRef.current.selectAll();
      const content = terminalRef.current.getSelection();
      terminalRef.current.clearSelection();
      return content;
    },
    sendInput: (data: string) => {
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        wsRef.current.send(data);
      }
    },
    status,
  }), [status]);

  // Handle resize - always fit the terminal, send dims only if WS connected
  const handleResize = useCallback(() => {
    if (fitAddonRef.current && terminalRef.current) {
      fitAddonRef.current.fit();

      // Only send resize to backend if WS is connected
      if (wsRef.current?.readyState === WebSocket.OPEN) {
        const dims = fitAddonRef.current.proposeDimensions();
        if (dims) {
          wsRef.current.send(
            JSON.stringify({
              resize: { cols: dims.cols, rows: dims.rows },
            })
          );
        }
      }
    }
  }, []);

  // Initialize terminal
  useEffect(() => {
    let mounted = true;

    async function initTerminal() {
      if (!containerRef.current) return;

      // Dynamic import xterm modules
      const xtermModule = await import("@xterm/xterm");
      const fitModule = await import("@xterm/addon-fit");
      const webLinksModule = await import("@xterm/addon-web-links");
      const clipboardModule = await import("@xterm/addon-clipboard");

      if (!mounted) return;

      Terminal = xtermModule.Terminal;
      FitAddon = fitModule.FitAddon;
      WebLinksAddon = webLinksModule.WebLinksAddon;
      ClipboardAddon = clipboardModule.ClipboardAddon;

      // Create terminal
      const term = new Terminal({
        cursorBlink: true,
        fontSize: fontSize,
        fontFamily: fontFamily,
        scrollback: 5000, // Enable scrollback buffer (5000 lines)
        // Force selection to work even if shell has mouse mode enabled
        allowProposedApi: true,
        rightClickSelectsWord: true,
        // Alt+click forces selection on Windows/Linux, Option+click on Mac
        macOptionClickForcesSelection: true,
        altClickMovesCursor: false,
        theme: {
          background: "#0f172a", // slate-900
          foreground: "#e2e8f0", // slate-200
          cursor: "#4ade80", // green-400
          cursorAccent: "#0f172a",
          selectionBackground: "#334155", // slate-700
          black: "#1e293b",
          red: "#f87171",
          green: "#4ade80",
          yellow: "#facc15",
          blue: "#60a5fa",
          magenta: "#c084fc",
          cyan: "#22d3ee",
          white: "#f1f5f9",
          brightBlack: "#475569",
          brightRed: "#fca5a5",
          brightGreen: "#86efac",
          brightYellow: "#fde047",
          brightBlue: "#93c5fd",
          brightMagenta: "#d8b4fe",
          brightCyan: "#67e8f9",
          brightWhite: "#f8fafc",
        },
      });

      // Create addons
      const fitAddon = new FitAddon();
      const webLinksAddon = new WebLinksAddon();
      const clipboardAddon = new ClipboardAddon();

      term.loadAddon(fitAddon);
      term.loadAddon(webLinksAddon);
      term.loadAddon(clipboardAddon);

      // Open terminal in container
      term.open(containerRef.current);

      terminalRef.current = term;
      fitAddonRef.current = fitAddon;

      // Mobile-specific setup: suppress native keyboard (we use custom keyboard)
      if (isMobileDevice()) {
        const textarea = containerRef.current.querySelector<HTMLTextAreaElement>(".xterm-helper-textarea");
        if (textarea) {
          textarea.inputMode = "none";
          textarea.readOnly = true;
        }

        // Prevent pull-to-refresh via CSS
        containerRef.current.style.overscrollBehavior = 'none';
        containerRef.current.style.touchAction = 'none';

        // Touch scrolling - send scroll commands to tmux via WebSocket
        let touchStartY = 0;
        let lastSentY = 0;
        let inCopyMode = false;
        const SCROLL_THRESHOLD = 50; // pixels per scroll command
        const container = containerRef.current;

        const handleTouchStart = (e: TouchEvent) => {
          // Only handle touches inside our container
          if (!container.contains(e.target as Node)) return;

          touchStartY = e.touches[0].clientY;
          lastSentY = touchStartY;

          // Enter tmux copy-mode immediately on touch
          if (!inCopyMode && wsRef.current?.readyState === WebSocket.OPEN) {
            wsRef.current.send('\x02['); // Ctrl+b [
            inCopyMode = true;
          }
        };

        const handleTouchMove = (e: TouchEvent) => {
          // Only handle touches inside our container
          if (!container.contains(e.target as Node)) return;

          e.preventDefault(); // Prevent pull-to-refresh
          e.stopPropagation();

          const currentY = e.touches[0].clientY;
          const deltaY = lastSentY - currentY;

          // Only scroll if we've moved enough
          if (Math.abs(deltaY) >= SCROLL_THRESHOLD) {
            // Send scroll commands using Ctrl+U (half page up) and Ctrl+D (half page down)
            // Natural scrolling: swipe up = see older content (scroll up), swipe down = see newer content
            if (wsRef.current?.readyState === WebSocket.OPEN) {
              if (deltaY > 0) {
                // Finger moving up - natural scroll: go down in history (Ctrl+D)
                wsRef.current.send('\x04'); // Ctrl+D
              } else {
                // Finger moving down - natural scroll: go up in history (Ctrl+U)
                wsRef.current.send('\x15'); // Ctrl+U
              }
            }

            lastSentY = currentY;
          }
        };

        const handleTouchEnd = () => {
          // Reset for next touch
          touchStartY = 0;
          lastSentY = 0;
          // Keep copy mode active so user can continue scrolling
        };

        // Use document-level listeners with capture to intercept before browser
        document.addEventListener('touchstart', handleTouchStart, { passive: true, capture: true });
        document.addEventListener('touchmove', handleTouchMove, { passive: false, capture: true });
        document.addEventListener('touchend', handleTouchEnd, { passive: true, capture: true });

        // Store cleanup
        (term as unknown as { _touchCleanup?: () => void })._touchCleanup = () => {
          document.removeEventListener('touchstart', handleTouchStart, { capture: true });
          document.removeEventListener('touchmove', handleTouchMove, { capture: true });
          document.removeEventListener('touchend', handleTouchEnd, { capture: true });
        };
      }

      // Fit immediately and again after a short delay to ensure proper sizing
      fitAddon.fit();
      setTimeout(() => {
        if (mounted && fitAddonRef.current) {
          fitAddonRef.current.fit();
        }
      }, 100);

      // Connect to WebSocket with timeout and auto-retry
      const CONNECTION_TIMEOUT = 10000; // 10 seconds
      const RETRY_BACKOFF = 2000; // 2 seconds
      let hasRetried = false;

      function connectWebSocket() {
        // WebSocket needs to connect directly to backend, not through Next.js
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        let wsHost: string;

        // Map frontend hosts to their backend WebSocket endpoints
        // Standalone terminal app: frontend on 3002, backend on 8002
        if (window.location.host === "terminal.summitflow.dev") {
          // Production: frontend on terminal.summitflow.dev → backend on terminalapi.summitflow.dev
          wsHost = "terminalapi.summitflow.dev";
        } else if (window.location.host.includes("localhost")) {
          // Local development: connect to terminal backend on port 8002
          wsHost = "localhost:8002";
        } else {
          // Default: same host (for local dev or other setups)
          wsHost = window.location.host;
        }

        let wsUrl = `${protocol}//${wsHost}/ws/terminal/${sessionId}`;
        if (workingDir) {
          wsUrl += `?working_dir=${encodeURIComponent(workingDir)}`;
        }

        const ws = new WebSocket(wsUrl);
        wsRef.current = ws;

        // Connection timeout
        const timeoutId = setTimeout(() => {
          if (ws.readyState === WebSocket.CONNECTING) {
            ws.close();
            if (!mounted) return;

            if (!hasRetried) {
              // Auto-retry once with backoff
              hasRetried = true;
              term.writeln("\x1b[33mConnection timeout, retrying...\x1b[0m");
              setStatus("connecting");
              setTimeout(() => {
                if (mounted) {
                  connectWebSocket();
                }
              }, RETRY_BACKOFF);
            } else {
              // Second timeout - give up
              setStatus("timeout");
              term.writeln("\r\n\x1b[31mConnection timeout\x1b[0m");
              onDisconnect?.();
            }
          }
        }, CONNECTION_TIMEOUT);

        ws.onopen = () => {
          clearTimeout(timeoutId);
          if (!mounted) return;
          setStatus("connected");
          term.writeln("Connected to terminal session: " + sessionId);
          term.writeln("");

          // Send initial size
          const dims = fitAddon.proposeDimensions();
          if (dims) {
            ws.send(
              JSON.stringify({
                resize: { cols: dims.cols, rows: dims.rows },
              })
            );
          }
        };

        ws.onmessage = (event) => {
          if (!mounted) return;
          term.write(event.data);
        };

        ws.onclose = (event) => {
          clearTimeout(timeoutId);
          if (!mounted) return;

          // Check for session_dead error (code 4000)
          if (event.code === 4000) {
            setStatus("session_dead");
            try {
              const reason = JSON.parse(event.reason);
              term.writeln(`\r\n\x1b[31m${reason.message || "Session not found"}\x1b[0m`);
            } catch {
              term.writeln("\r\n\x1b[31mSession not found or could not be restored\x1b[0m");
            }
          } else {
            setStatus("disconnected");
            term.writeln("\r\n\x1b[31mDisconnected from terminal\x1b[0m");
          }

          onDisconnect?.();
        };

        ws.onerror = () => {
          clearTimeout(timeoutId);
          if (!mounted) return;
          setStatus("error");
          term.writeln("\r\n\x1b[31mConnection error\x1b[0m");
        };

        // Handle terminal input
        term.onData((data) => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send(data);
          }
        });
      }

      // Store reference for reconnection
      connectWebSocketRef.current = connectWebSocket;
      connectWebSocket();

      // Handle window resize
      window.addEventListener("resize", handleResize);
    }

    initTerminal();

    return () => {
      mounted = false;
      window.removeEventListener("resize", handleResize);

      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }

      if (terminalRef.current) {
        // Clean up touch handlers
        const touchCleanup = (terminalRef.current as unknown as { _touchCleanup?: () => void })._touchCleanup;
        if (touchCleanup) touchCleanup();

        terminalRef.current.dispose();
        terminalRef.current = null;
      }
    };
    // NOTE: fontFamily/fontSize intentionally omitted - they're handled by separate effect (line 239-249)
    // Including them here would cause terminal to reinitialize on font changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, workingDir, handleResize, onDisconnect]);

  // Handle container resize with debounce to prevent loops
  useEffect(() => {
    if (!containerRef.current) return;

    let resizeTimeout: ReturnType<typeof setTimeout> | null = null;
    let lastWidth = 0;
    let lastHeight = 0;

    const resizeObserver = new ResizeObserver((entries) => {
      // Only process if size actually changed (prevents loops)
      const entry = entries[0];
      if (!entry) return;

      const { width, height } = entry.contentRect;
      if (width === lastWidth && height === lastHeight) return;

      lastWidth = width;
      lastHeight = height;

      // Debounce resize to prevent rapid firing
      if (resizeTimeout) clearTimeout(resizeTimeout);
      resizeTimeout = setTimeout(() => {
        handleResize();
      }, 50);
    });

    resizeObserver.observe(containerRef.current);

    return () => {
      if (resizeTimeout) clearTimeout(resizeTimeout);
      resizeObserver.disconnect();
    };
  }, [handleResize]);

  // Update font settings when they change
  useEffect(() => {
    if (terminalRef.current) {
      terminalRef.current.options.fontFamily = fontFamily;
      terminalRef.current.options.fontSize = fontSize;
      // Refit after font change
      if (fitAddonRef.current) {
        fitAddonRef.current.fit();
      }
    }
  }, [fontFamily, fontSize]);

  return (
    <div className={clsx("relative overflow-hidden", className)}>
      {/* Status indicator - hidden on mobile (shown in control bar) */}
      <div className="absolute top-2 right-2 z-10 items-center gap-2 hidden md:flex">
        <span
          className={clsx("w-2 h-2 rounded-full", {
            "bg-yellow-400 animate-pulse": status === "connecting",
            "bg-green-400": status === "connected",
            "bg-gray-400": status === "disconnected",
            "bg-red-400": status === "error" || status === "timeout",
            "bg-orange-400": status === "session_dead",
          })}
        />
        <span className="text-xs text-slate-400">
          {status === "session_dead" ? "dead" : status}
        </span>
      </div>

      {/* Terminal container - no min-height to prevent overflow */}
      <div
        ref={containerRef}
        className="w-full h-full bg-slate-900 overflow-hidden"
      />
    </div>
  );
});
