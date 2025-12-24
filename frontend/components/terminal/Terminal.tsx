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
  suppressNativeKeyboard?: boolean;
}

export type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error" | "session_dead" | "timeout";

export interface TerminalHandle {
  reconnect: () => void;
  getContent: () => string;
  sendInput: (data: string) => void;
  status: ConnectionStatus;
}

export const TerminalComponent = forwardRef<TerminalHandle, TerminalProps>(function TerminalComponent({
  sessionId,
  workingDir,
  className,
  onDisconnect,
  onStatusChange,
  fontFamily = "'JetBrains Mono', monospace",
  fontSize = 14,
  suppressNativeKeyboard = false,
}, ref) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<InstanceType<typeof Terminal> | null>(null);
  const fitAddonRef = useRef<InstanceType<typeof FitAddon> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");
  const connectWebSocketRef = useRef<(() => void) | null>(null);

  // Notify parent of status changes
  useEffect(() => {
    onStatusChange?.(status);
  }, [status, onStatusChange]);

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
        if (window.location.host === "dev.summitflow.dev") {
          wsHost = "devapi.summitflow.dev";
        } else if (window.location.host.includes("localhost:3001")) {
          wsHost = "localhost:8001";
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
        terminalRef.current.dispose();
        terminalRef.current = null;
      }
    };
    // NOTE: fontFamily/fontSize intentionally omitted - they're handled by separate effect (line 239-249)
    // Including them here would cause terminal to reinitialize on font changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionId, workingDir, handleResize, onDisconnect]);

  // Handle container resize
  useEffect(() => {
    if (!containerRef.current) return;

    const resizeObserver = new ResizeObserver(() => {
      handleResize();
    });

    resizeObserver.observe(containerRef.current);

    return () => {
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

  // Apply keyboard suppression when enabled (for custom keyboard mode)
  useEffect(() => {
    if (!containerRef.current || !suppressNativeKeyboard) return;

    // Find the xterm helper textarea
    const textarea = containerRef.current.querySelector<HTMLTextAreaElement>(".xterm-helper-textarea");
    if (!textarea) return;

    // Apply suppression techniques
    const originalInputMode = textarea.inputMode;
    const originalReadOnly = textarea.readOnly;

    // Tier 1: inputMode="none" (works on most mobile browsers)
    textarea.inputMode = "none";

    // Tier 2: readonly fallback
    textarea.readOnly = true;

    // Cleanup on unmount or when suppression is disabled
    return () => {
      textarea.inputMode = originalInputMode;
      textarea.readOnly = originalReadOnly;
    };
  }, [suppressNativeKeyboard]);

  return (
    <div className={clsx("relative overflow-hidden", className)}>
      {/* Status indicator */}
      <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
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
        className={clsx(
          "w-full h-full",
          "bg-slate-900 overflow-hidden"
        )}
        style={{
          overscrollBehavior: "contain",
          touchAction: "none",
        }}
        onTouchMove={(e) => e.stopPropagation()}
      />
    </div>
  );
});
