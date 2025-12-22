'use client';

import { useState, useEffect, useRef } from 'react';
import { clsx } from 'clsx';

type ConnectionStatus = 'connected' | 'reconnecting' | 'disconnected';

interface MemoryCaptureIndicatorProps {
  projectId: string;
  className?: string;
}

/**
 * Small status dot indicating memory capture connection status.
 * Designed to be unobtrusive - just a pulsing dot with tooltip.
 */
export function MemoryCaptureIndicator({
  projectId,
  className,
}: MemoryCaptureIndicatorProps) {
  const [status, setStatus] = useState<ConnectionStatus>('disconnected');
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const [showTooltip, setShowTooltip] = useState(false);

  useEffect(() => {
    const connect = () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }

      setStatus('reconnecting');

      const url = `/api/projects/${projectId}/observations/stream`;
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      eventSource.addEventListener('connected', () => {
        setStatus('connected');
      });

      eventSource.addEventListener('heartbeat', () => {
        // Keep alive, ensure we're marked as connected
        if (status !== 'connected') {
          setStatus('connected');
        }
      });

      eventSource.onerror = () => {
        setStatus('disconnected');
        eventSource.close();
        eventSourceRef.current = null;

        // Reconnect after delay
        if (!reconnectTimeoutRef.current) {
          reconnectTimeoutRef.current = setTimeout(() => {
            reconnectTimeoutRef.current = null;
            connect();
          }, 5000);
        }
      };
    };

    connect();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [projectId, status]);

  const statusConfig = {
    connected: {
      color: 'bg-emerald-400',
      shadow: 'shadow-[0_0_6px_rgba(52,211,153,0.6)]',
      pulse: true,
      text: 'Memory capture active',
    },
    reconnecting: {
      color: 'bg-amber-400',
      shadow: 'shadow-[0_0_6px_rgba(251,191,36,0.6)]',
      pulse: false,
      text: 'Reconnecting...',
    },
    disconnected: {
      color: 'bg-rose-400',
      shadow: 'shadow-[0_0_6px_rgba(251,113,133,0.6)]',
      pulse: false,
      text: 'Memory capture disconnected',
    },
  };

  const config = statusConfig[status];

  return (
    <div
      className={clsx('relative', className)}
      onMouseEnter={() => setShowTooltip(true)}
      onMouseLeave={() => setShowTooltip(false)}
    >
      {/* Status dot */}
      <span
        className={clsx(
          'w-2 h-2 rounded-full block',
          config.color,
          config.shadow,
          config.pulse && 'animate-pulse'
        )}
      />

      {/* Tooltip */}
      {showTooltip && (
        <div className="absolute top-full left-1/2 -translate-x-1/2 mt-2 z-50">
          <div className="px-2 py-1 text-xs bg-slate-800 border border-slate-700 rounded shadow-lg whitespace-nowrap">
            {config.text}
          </div>
        </div>
      )}
    </div>
  );
}
