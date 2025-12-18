/**
 * PageDetail - Detail panel for frontend pages
 *
 * Shows route info, health, performance, and console errors.
 */

import { cn } from "@/lib/utils";
import type { ExplorerEntry } from "@/lib/api/explorer";

interface PageDetailProps {
  entry: ExplorerEntry;
}

const formatDate = (dateStr: string | undefined | null) => {
  if (!dateStr) return "-";
  return new Date(dateStr).toLocaleString();
};

const formatDuration = (ms: number | undefined | null) => {
  if (ms === undefined || ms === null) return "-";
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(2)}s`;
};

export function PageDetail({ entry }: PageDetailProps) {
  const meta = entry.metadata;
  const consoleErrors = meta.console_errors ?? 0;
  const consoleWarnings = meta.console_warnings ?? 0;
  const routeParams = meta.route_params ?? [];

  return (
    <div className="space-y-4">
      {/* Route */}
      <div>
        <span className="text-xs text-slate-500 uppercase tracking-wide">Route</span>
        <p className="font-mono text-sm text-slate-300 mt-1">{entry.path}</p>
      </div>

      {/* Source */}
      {meta.source_file && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">Source</span>
          <p className="font-mono text-sm text-slate-300 mt-1">{meta.source_file}</p>
        </div>
      )}

      {/* Route params */}
      {routeParams.length > 0 && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">
            Route Parameters
          </span>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {routeParams.map((param: string) => (
              <span
                key={param}
                className="px-2 py-0.5 rounded text-xs font-mono bg-purple-500/10 text-purple-400"
              >
                :{param}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Stats grid */}
      <div className="grid grid-cols-2 sm:grid-cols-3 gap-4">
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">Port</span>
          <p className="font-mono text-sm text-slate-200 mt-1">{meta.port ?? 3001}</p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">Status</span>
          <p
            className={cn(
              "font-mono text-sm mt-1",
              meta.http_status !== undefined && meta.http_status >= 200 && meta.http_status < 400
                ? "text-emerald-400"
                : meta.http_status !== undefined && meta.http_status >= 400
                ? "text-red-400"
                : "text-slate-200"
            )}
          >
            {meta.http_status ?? "-"}
          </p>
        </div>
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">Response</span>
          <p
            className={cn(
              "font-mono text-sm mt-1",
              meta.response_time_ms !== undefined && meta.response_time_ms > 1000
                ? "text-amber-400"
                : "text-slate-200"
            )}
          >
            {formatDuration(meta.response_time_ms)}
          </p>
        </div>
      </div>

      {/* Console output */}
      {(consoleErrors > 0 || consoleWarnings > 0) && (
        <div className="flex gap-4">
          {consoleErrors > 0 && (
            <div className="px-3 py-2 rounded bg-red-500/10 border border-red-500/20">
              <span className="text-xs text-red-400 font-medium">
                {consoleErrors} Console Error{consoleErrors > 1 ? "s" : ""}
              </span>
            </div>
          )}
          {consoleWarnings > 0 && (
            <div className="px-3 py-2 rounded bg-amber-500/10 border border-amber-500/20">
              <span className="text-xs text-amber-400 font-medium">
                {consoleWarnings} Console Warning{consoleWarnings > 1 ? "s" : ""}
              </span>
            </div>
          )}
        </div>
      )}

      {/* Last health check */}
      {meta.last_health_check && (
        <div>
          <span className="text-xs text-slate-500 uppercase tracking-wide">Last Check</span>
          <p className="text-sm text-slate-400 mt-1">{formatDate(meta.last_health_check)}</p>
        </div>
      )}
    </div>
  );
}
