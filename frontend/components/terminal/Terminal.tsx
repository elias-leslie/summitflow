"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { clsx } from "clsx";

// Dynamic imports for xterm (client-side only)
let Terminal: typeof import("@xterm/xterm").Terminal;
let FitAddon: typeof import("@xterm/addon-fit").FitAddon;
let WebLinksAddon: typeof import("@xterm/addon-web-links").WebLinksAddon;

interface TerminalProps {
  sessionId: string;
  workingDir?: string;
  className?: string;
  onDisconnect?: () => void;
}

type ConnectionStatus = "connecting" | "connected" | "disconnected" | "error";

export function TerminalComponent({
  sessionId,
  workingDir,
  className,
  onDisconnect,
}: TerminalProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const terminalRef = useRef<InstanceType<typeof Terminal> | null>(null);
  const fitAddonRef = useRef<InstanceType<typeof FitAddon> | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const [status, setStatus] = useState<ConnectionStatus>("connecting");

  // Handle resize
  const handleResize = useCallback(() => {
    if (fitAddonRef.current && terminalRef.current && wsRef.current?.readyState === WebSocket.OPEN) {
      fitAddonRef.current.fit();
      const dims = fitAddonRef.current.proposeDimensions();
      if (dims) {
        wsRef.current.send(
          JSON.stringify({
            resize: { cols: dims.cols, rows: dims.rows },
          })
        );
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

      if (!mounted) return;

      Terminal = xtermModule.Terminal;
      FitAddon = fitModule.FitAddon;
      WebLinksAddon = webLinksModule.WebLinksAddon;

      // Create terminal
      const term = new Terminal({
        cursorBlink: true,
        fontSize: 14,
        fontFamily: 'Menlo, Monaco, "Courier New", monospace',
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

      term.loadAddon(fitAddon);
      term.loadAddon(webLinksAddon);

      // Open terminal in container
      term.open(containerRef.current);
      fitAddon.fit();

      terminalRef.current = term;
      fitAddonRef.current = fitAddon;

      // Connect to WebSocket
      const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
      const host = window.location.host;
      let wsUrl = `${protocol}//${host}/ws/terminal/${sessionId}`;
      if (workingDir) {
        wsUrl += `?working_dir=${encodeURIComponent(workingDir)}`;
      }

      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
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

      ws.onclose = () => {
        if (!mounted) return;
        setStatus("disconnected");
        term.writeln("\r\n\x1b[31mDisconnected from terminal\x1b[0m");
        onDisconnect?.();
      };

      ws.onerror = () => {
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

  return (
    <div className={clsx("relative", className)}>
      {/* Status indicator */}
      <div className="absolute top-2 right-2 z-10 flex items-center gap-2">
        <span
          className={clsx("w-2 h-2 rounded-full", {
            "bg-yellow-400 animate-pulse": status === "connecting",
            "bg-green-400": status === "connected",
            "bg-gray-400": status === "disconnected",
            "bg-red-400": status === "error",
          })}
        />
        <span className="text-xs text-slate-400">{status}</span>
      </div>

      {/* Terminal container */}
      <div
        ref={containerRef}
        className={clsx(
          "w-full h-full min-h-[300px]",
          "bg-slate-900 rounded-lg overflow-hidden",
          "border border-slate-700"
        )}
      />
    </div>
  );
}
