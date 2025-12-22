"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { clsx } from "clsx";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { ScrollArea } from "../ui/scroll-area";
import {
  Brain,
  ChevronDown,
  ChevronUp,
  Zap,
  RefreshCw,
  WifiOff,
  Clock,
  Tag,
  FileCode,
  AlertCircle,
} from "lucide-react";

// Observation types from the plan
type ObservationType =
  | "bugfix"
  | "feature"
  | "refactor"
  | "change"
  | "discovery"
  | "decision";

// Concept types from the plan
type ConceptType =
  | "how-it-works"
  | "why-it-exists"
  | "what-changed"
  | "problem-solution"
  | "gotcha"
  | "pattern"
  | "trade-off";

interface Observation {
  id: string;
  project_id: string;
  session_id: string;
  agent_type: string;
  observation_type: ObservationType;
  concepts: ConceptType[];
  title: string;
  subtitle: string | null;
  narrative: string | null;
  facts: Record<string, unknown>[] | null;
  files_read: string[] | null;
  files_modified: string[] | null;
  tool_name: string;
  tool_input: Record<string, unknown> | null;
  discovery_tokens: number | null;
  created_at: string;
}

interface MemoryStreamPanelProps {
  projectId: string;
  sessionId?: string;
  className?: string;
}

// Color mapping for observation types
const OBSERVATION_TYPE_COLORS: Record<ObservationType, string> = {
  bugfix: "bg-red-500/10 text-red-500 border-red-500/20",
  feature: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
  refactor: "bg-blue-500/10 text-blue-500 border-blue-500/20",
  change: "bg-amber-500/10 text-amber-500 border-amber-500/20",
  discovery: "bg-purple-500/10 text-purple-500 border-purple-500/20",
  decision: "bg-cyan-500/10 text-cyan-500 border-cyan-500/20",
};

// Color mapping for concepts
const CONCEPT_COLORS: Record<ConceptType, string> = {
  "how-it-works": "bg-slate-500/10 text-slate-500",
  "why-it-exists": "bg-indigo-500/10 text-indigo-400",
  "what-changed": "bg-amber-500/10 text-amber-400",
  "problem-solution": "bg-emerald-500/10 text-emerald-400",
  gotcha: "bg-red-500/10 text-red-400",
  pattern: "bg-blue-500/10 text-blue-400",
  "trade-off": "bg-purple-500/10 text-purple-400",
};

export function MemoryStreamPanel({
  projectId,
  sessionId,
  className,
}: MemoryStreamPanelProps) {
  const [observations, setObservations] = useState<Observation[]>([]);
  const [expandedIds, setExpandedIds] = useState<Set<string>>(new Set());
  const [connected, setConnected] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const scrollAreaRef = useRef<HTMLDivElement>(null);

  // Connect to SSE stream
  const connect = useCallback(() => {
    if (eventSourceRef.current) {
      eventSourceRef.current.close();
    }

    setReconnecting(true);
    setError(null);

    const url = `/api/projects/${projectId}/observations/stream`;
    const eventSource = new EventSource(url);
    eventSourceRef.current = eventSource;

    eventSource.addEventListener("connected", () => {
      setConnected(true);
      setReconnecting(false);
      setError(null);
    });

    eventSource.addEventListener("observation", (event) => {
      try {
        const observation = JSON.parse(event.data) as Observation;

        // Filter by session if specified
        if (sessionId && observation.session_id !== sessionId) {
          return;
        }

        setObservations((prev) => {
          // Avoid duplicates
          if (prev.some((o) => o.id === observation.id)) {
            return prev;
          }
          // Add to front (newest first)
          return [observation, ...prev].slice(0, 100); // Keep max 100
        });
      } catch (err) {
        console.error("Failed to parse observation:", err);
      }
    });

    eventSource.addEventListener("heartbeat", () => {
      // Keep alive, no action needed
    });

    eventSource.onerror = () => {
      setConnected(false);
      setReconnecting(false);
      eventSource.close();

      // Reconnect after delay
      if (!reconnectTimeoutRef.current) {
        reconnectTimeoutRef.current = setTimeout(() => {
          reconnectTimeoutRef.current = null;
          connect();
        }, 5000);
      }
    };
  }, [projectId, sessionId]);

  // Initial connection and cleanup
  useEffect(() => {
    connect();

    return () => {
      if (eventSourceRef.current) {
        eventSourceRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [connect]);

  // Load initial observations
  useEffect(() => {
    const loadInitial = async () => {
      try {
        const params = new URLSearchParams({ limit: "50" });
        if (sessionId) {
          params.set("session_id", sessionId);
        }

        const response = await fetch(
          `/api/projects/${projectId}/observations?${params}`
        );
        if (response.ok) {
          const data = await response.json();
          setObservations(data);
        }
      } catch (err) {
        console.error("Failed to load observations:", err);
      }
    };

    loadInitial();
  }, [projectId, sessionId]);

  const toggleExpanded = (id: string) => {
    setExpandedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const formatTime = (dateStr: string) => {
    const date = new Date(dateStr);
    return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  };

  const estimateTokens = (text: string | null | undefined): number => {
    if (!text) return 0;
    return Math.ceil(text.length / 4);
  };

  return (
    <div className={clsx("flex flex-col h-full", className)}>
      {/* Header */}
      <div className="flex items-center justify-between p-3 border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center gap-2">
          <Brain className="h-4 w-4 text-purple-500" />
          <span className="text-sm font-medium">Memory Stream</span>
        </div>
        <div className="flex items-center gap-2">
          {connected ? (
            <Badge variant="outline" className="bg-emerald-500/10 text-emerald-500 text-xs">
              <Zap className="h-3 w-3 mr-1" />
              Live
            </Badge>
          ) : reconnecting ? (
            <Badge variant="outline" className="bg-amber-500/10 text-amber-500 text-xs">
              <RefreshCw className="h-3 w-3 mr-1 animate-spin" />
              Reconnecting
            </Badge>
          ) : (
            <Badge variant="outline" className="bg-red-500/10 text-red-500 text-xs">
              <WifiOff className="h-3 w-3 mr-1" />
              Disconnected
            </Badge>
          )}
        </div>
      </div>

      {/* Error message */}
      {error && (
        <div className="p-2 bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 text-xs flex items-center gap-2">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </div>
      )}

      {/* Observations list */}
      <ScrollArea ref={scrollAreaRef} className="flex-1 p-3">
        {observations.length === 0 ? (
          <div className="text-center py-8 text-slate-500 text-sm">
            <Brain className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>No observations yet</p>
            <p className="text-xs mt-1">Tool executions will appear here</p>
          </div>
        ) : (
          <div className="space-y-2">
            {observations.map((obs) => (
              <ObservationCard
                key={obs.id}
                observation={obs}
                expanded={expandedIds.has(obs.id)}
                onToggle={() => toggleExpanded(obs.id)}
                formatTime={formatTime}
                estimateTokens={estimateTokens}
              />
            ))}
          </div>
        )}
      </ScrollArea>
    </div>
  );
}

// Individual observation card
interface ObservationCardProps {
  observation: Observation;
  expanded: boolean;
  onToggle: () => void;
  formatTime: (date: string) => string;
  estimateTokens: (text: string | null | undefined) => number;
}

function ObservationCard({
  observation,
  expanded,
  onToggle,
  formatTime,
  estimateTokens,
}: ObservationCardProps) {
  const typeColor =
    OBSERVATION_TYPE_COLORS[observation.observation_type] ||
    "bg-slate-500/10 text-slate-500";

  const totalTokens =
    (observation.discovery_tokens ?? 0) ||
    estimateTokens(observation.narrative) +
      estimateTokens(observation.title) +
      estimateTokens(observation.subtitle);

  return (
    <Card className="overflow-hidden">
      <CardHeader className="p-3 pb-2">
        <div className="flex items-start justify-between gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge variant="outline" className={clsx("text-xs", typeColor)}>
              {observation.observation_type}
            </Badge>
            <span className="text-xs text-slate-500">
              {observation.agent_type}
            </span>
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-500">
            <Clock className="h-3 w-3" />
            {formatTime(observation.created_at)}
            <Button
              variant="ghost"
              size="sm"
              onClick={onToggle}
              className="h-6 w-6 p-0"
            >
              {expanded ? (
                <ChevronUp className="h-3.5 w-3.5" />
              ) : (
                <ChevronDown className="h-3.5 w-3.5" />
              )}
            </Button>
          </div>
        </div>
        <CardTitle className="text-sm leading-tight mt-1.5">
          {observation.title}
        </CardTitle>
        {observation.subtitle && (
          <p className="text-xs text-slate-500 mt-0.5">{observation.subtitle}</p>
        )}
      </CardHeader>

      <CardContent className="p-3 pt-0 space-y-2">
        {/* Concept tags */}
        {observation.concepts && observation.concepts.length > 0 && (
          <div className="flex flex-wrap gap-1">
            {observation.concepts.map((concept) => (
              <Badge
                key={concept}
                variant="outline"
                className={clsx(
                  "text-xs",
                  CONCEPT_COLORS[concept] || "bg-slate-500/10 text-slate-500"
                )}
              >
                <Tag className="h-2.5 w-2.5 mr-1" />
                {concept}
              </Badge>
            ))}
          </div>
        )}

        {/* Token estimate */}
        <div className="text-xs text-slate-400">~{totalTokens} tokens</div>

        {/* Expanded details */}
        {expanded && (
          <div className="space-y-3 pt-2 border-t border-slate-200 dark:border-slate-800">
            {/* Narrative */}
            {observation.narrative && (
              <div>
                <h4 className="text-xs font-medium text-slate-500 mb-1">
                  Narrative
                </h4>
                <p className="text-sm text-slate-700 dark:text-slate-300 whitespace-pre-wrap">
                  {observation.narrative}
                </p>
              </div>
            )}

            {/* Facts */}
            {observation.facts && observation.facts.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-slate-500 mb-1">
                  Facts
                </h4>
                <ul className="text-xs text-slate-600 dark:text-slate-400 space-y-1 list-disc list-inside">
                  {observation.facts.map((fact, i) => (
                    <li key={i}>{JSON.stringify(fact)}</li>
                  ))}
                </ul>
              </div>
            )}

            {/* Files modified */}
            {observation.files_modified && observation.files_modified.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-slate-500 mb-1 flex items-center gap-1">
                  <FileCode className="h-3 w-3" />
                  Files Modified
                </h4>
                <div className="flex flex-wrap gap-1">
                  {observation.files_modified.map((file, i) => (
                    <Badge key={i} variant="outline" className="text-xs font-mono">
                      {file.split("/").pop()}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Tool info */}
            <div className="text-xs text-slate-400">
              Tool: {observation.tool_name}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
