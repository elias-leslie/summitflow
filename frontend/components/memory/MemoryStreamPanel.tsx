"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import { clsx } from "clsx";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { ScrollArea } from "../ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "../ui/tabs";
import { Progress } from "../ui/progress";
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
  Filter,
  X,
  Database,
  Layers,
  Loader2,
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

// Context index types
interface ContextItem {
  id: string;
  type: string;
  title: string;
  summary?: string;
  token_estimate: number;
  created_at?: string;
}

interface ContextIndex {
  project_id: string;
  session_id: string | null;
  items: ContextItem[];
  item_count: number;
  index_tokens: number;
  full_tokens: number;
  reduction_pct: number;
  from_cache: boolean;
  instructions: string;
}

interface ExpandedContent {
  entity_id: string;
  type: string;
  content: Record<string, unknown>;
  token_count: number;
}

// Token limit for display (configurable)
const TOKEN_LIMIT = 8000;

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

// All observation types for filtering
const OBSERVATION_TYPES: ObservationType[] = [
  "bugfix",
  "feature",
  "refactor",
  "change",
  "discovery",
  "decision",
];

// All concept types for filtering
const CONCEPT_TYPES: ConceptType[] = [
  "how-it-works",
  "why-it-exists",
  "what-changed",
  "problem-solution",
  "gotcha",
  "pattern",
  "trade-off",
];

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

  // Filtering state
  const [typeFilter, setTypeFilter] = useState<ObservationType | "all">("all");
  const [conceptFilters, setConceptFilters] = useState<Set<ConceptType>>(new Set());
  const [showFilters, setShowFilters] = useState(false);

  // Tab state
  const [activeTab, setActiveTab] = useState<"stream" | "context">("stream");

  // Context tab state
  const [contextIndex, setContextIndex] = useState<ContextIndex | null>(null);
  const [contextLoading, setContextLoading] = useState(false);
  const [contextError, setContextError] = useState<string | null>(null);
  const [expandedContextIds, setExpandedContextIds] = useState<Set<string>>(new Set());
  const [expandedContents, setExpandedContents] = useState<Map<string, ExpandedContent>>(new Map());
  const [expandingIds, setExpandingIds] = useState<Set<string>>(new Set());

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

  // Toggle concept filter
  const toggleConceptFilter = (concept: ConceptType) => {
    setConceptFilters((prev) => {
      const next = new Set(prev);
      if (next.has(concept)) {
        next.delete(concept);
      } else {
        next.add(concept);
      }
      return next;
    });
  };

  // Clear all filters
  const clearFilters = () => {
    setTypeFilter("all");
    setConceptFilters(new Set());
  };

  // Check if any filters are active
  const hasActiveFilters = typeFilter !== "all" || conceptFilters.size > 0;

  // Filter observations
  const filteredObservations = observations.filter((obs) => {
    // Type filter
    if (typeFilter !== "all" && obs.observation_type !== typeFilter) {
      return false;
    }

    // Concept filter (if any concept filters selected, at least one must match)
    if (conceptFilters.size > 0) {
      const obsConcepts = obs.concepts || [];
      const hasMatchingConcept = obsConcepts.some((c) => conceptFilters.has(c));
      if (!hasMatchingConcept) {
        return false;
      }
    }

    return true;
  });

  // Load context index
  const loadContextIndex = useCallback(async () => {
    setContextLoading(true);
    setContextError(null);

    try {
      const params = new URLSearchParams();
      if (sessionId) {
        params.set("session_id", sessionId);
      }

      const response = await fetch(
        `/api/projects/${projectId}/context/index?${params}`
      );

      if (!response.ok) {
        throw new Error(`Failed to load context: ${response.status}`);
      }

      const data = await response.json();
      setContextIndex(data);
    } catch (err) {
      setContextError(err instanceof Error ? err.message : "Failed to load context");
    } finally {
      setContextLoading(false);
    }
  }, [projectId, sessionId]);

  // Load context when switching to Context tab
  useEffect(() => {
    if (activeTab === "context" && !contextIndex && !contextLoading) {
      loadContextIndex();
    }
  }, [activeTab, contextIndex, contextLoading, loadContextIndex]);

  // Expand a context item
  const expandContextItem = async (entityId: string) => {
    // Toggle if already expanded
    if (expandedContextIds.has(entityId)) {
      setExpandedContextIds((prev) => {
        const next = new Set(prev);
        next.delete(entityId);
        return next;
      });
      return;
    }

    // Check if already have the content
    if (expandedContents.has(entityId)) {
      setExpandedContextIds((prev) => new Set(prev).add(entityId));
      return;
    }

    // Fetch the content
    setExpandingIds((prev) => new Set(prev).add(entityId));

    try {
      const response = await fetch(`/api/projects/${projectId}/context/expand`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ entity_id: entityId }),
      });

      if (!response.ok) {
        throw new Error(`Failed to expand: ${response.status}`);
      }

      const data = await response.json();
      setExpandedContents((prev) => new Map(prev).set(entityId, data));
      setExpandedContextIds((prev) => new Set(prev).add(entityId));
    } catch (err) {
      console.error("Failed to expand context item:", err);
    } finally {
      setExpandingIds((prev) => {
        const next = new Set(prev);
        next.delete(entityId);
        return next;
      });
    }
  };

  // Get icon for context item type
  const getTypeIcon = (type: string) => {
    switch (type) {
      case "observation":
        return <Brain className="h-3.5 w-3.5" />;
      case "checkpoint":
        return <Clock className="h-3.5 w-3.5" />;
      case "pattern":
        return <Layers className="h-3.5 w-3.5" />;
      default:
        return <Database className="h-3.5 w-3.5" />;
    }
  };

  // Get color for context item type
  const getTypeColor = (type: string) => {
    switch (type) {
      case "observation":
        return "bg-purple-500/10 text-purple-500 border-purple-500/20";
      case "checkpoint":
        return "bg-amber-500/10 text-amber-500 border-amber-500/20";
      case "pattern":
        return "bg-blue-500/10 text-blue-500 border-blue-500/20";
      default:
        return "bg-slate-500/10 text-slate-500 border-slate-500/20";
    }
  };

  return (
    <div className={clsx("flex flex-col h-full", className)}>
      {/* Header with tabs */}
      <div className="border-b border-slate-200 dark:border-slate-800">
        <div className="flex items-center justify-between p-3 pb-0">
          <div className="flex items-center gap-2">
            <Brain className="h-4 w-4 text-purple-500" />
            <span className="text-sm font-medium">Memory</span>
          </div>
          <div className="flex items-center gap-2">
            {activeTab === "stream" && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setShowFilters(!showFilters)}
                className={clsx(
                  "h-7 w-7 p-0",
                  hasActiveFilters && "text-purple-500"
                )}
              >
                <Filter className="h-3.5 w-3.5" />
              </Button>
            )}
            {activeTab === "stream" && (
              connected ? (
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
              )
            )}
            {activeTab === "context" && (
              <Button
                variant="ghost"
                size="sm"
                onClick={loadContextIndex}
                disabled={contextLoading}
                className="h-7 w-7 p-0"
              >
                <RefreshCw className={clsx("h-3.5 w-3.5", contextLoading && "animate-spin")} />
              </Button>
            )}
          </div>
        </div>

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "stream" | "context")} className="px-3">
          <TabsList className="w-full grid grid-cols-2 h-8">
            <TabsTrigger value="stream" className="text-xs">
              Stream
              {hasActiveFilters && (
                <Badge variant="secondary" className="ml-1 text-[10px] h-4 px-1">
                  {filteredObservations.length}
                </Badge>
              )}
            </TabsTrigger>
            <TabsTrigger value="context" className="text-xs">
              Context
              {contextIndex && (
                <Badge variant="secondary" className="ml-1 text-[10px] h-4 px-1">
                  {contextIndex.item_count}
                </Badge>
              )}
            </TabsTrigger>
          </TabsList>
        </Tabs>
      </div>

      {/* Stream tab filters */}
      {activeTab === "stream" && showFilters && (
        <div className="p-3 border-b border-slate-200 dark:border-slate-800 space-y-3">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 w-12">Type:</span>
            <Select
              value={typeFilter}
              onValueChange={(value) => setTypeFilter(value as ObservationType | "all")}
            >
              <SelectTrigger className="h-7 text-xs w-32">
                <SelectValue placeholder="All types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All types</SelectItem>
                {OBSERVATION_TYPES.map((type) => (
                  <SelectItem key={type} value={type}>
                    {type}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          <div className="space-y-1">
            <span className="text-xs text-slate-500">Concepts:</span>
            <div className="flex flex-wrap gap-1">
              {CONCEPT_TYPES.map((concept) => {
                const isActive = conceptFilters.has(concept);
                return (
                  <Badge
                    key={concept}
                    variant="outline"
                    className={clsx(
                      "text-xs cursor-pointer transition-colors",
                      isActive
                        ? CONCEPT_COLORS[concept]
                        : "bg-slate-100 dark:bg-slate-800 text-slate-500 hover:bg-slate-200 dark:hover:bg-slate-700"
                    )}
                    onClick={() => toggleConceptFilter(concept)}
                  >
                    {concept}
                  </Badge>
                );
              })}
            </div>
          </div>

          {hasActiveFilters && (
            <Button
              variant="ghost"
              size="sm"
              onClick={clearFilters}
              className="h-6 text-xs text-slate-500"
            >
              <X className="h-3 w-3 mr-1" />
              Clear filters
            </Button>
          )}
        </div>
      )}

      {/* Stream tab error */}
      {activeTab === "stream" && error && (
        <div className="p-2 bg-red-50 dark:bg-red-950/30 text-red-600 dark:text-red-400 text-xs flex items-center gap-2">
          <AlertCircle className="h-3.5 w-3.5" />
          {error}
        </div>
      )}

      {/* Stream tab content */}
      {activeTab === "stream" && (
        <ScrollArea ref={scrollAreaRef} className="flex-1 p-3">
          {observations.length === 0 ? (
            <div className="text-center py-8 text-slate-500 text-sm">
              <Brain className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No observations yet</p>
              <p className="text-xs mt-1">Tool executions will appear here</p>
            </div>
          ) : filteredObservations.length === 0 ? (
            <div className="text-center py-8 text-slate-500 text-sm">
              <Filter className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No matching observations</p>
              <p className="text-xs mt-1">Try adjusting your filters</p>
            </div>
          ) : (
            <div className="space-y-2">
              {filteredObservations.map((obs) => (
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
      )}

      {/* Context tab content */}
      {activeTab === "context" && (
        <ScrollArea className="flex-1 p-3">
          {contextLoading ? (
            <div className="text-center py-8 text-slate-500 text-sm">
              <Loader2 className="h-8 w-8 mx-auto mb-2 animate-spin opacity-50" />
              <p>Loading context index...</p>
            </div>
          ) : contextError ? (
            <div className="text-center py-8 text-red-500 text-sm">
              <AlertCircle className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>{contextError}</p>
              <Button
                variant="outline"
                size="sm"
                onClick={loadContextIndex}
                className="mt-2"
              >
                Retry
              </Button>
            </div>
          ) : !contextIndex || contextIndex.items.length === 0 ? (
            <div className="text-center py-8 text-slate-500 text-sm">
              <Database className="h-8 w-8 mx-auto mb-2 opacity-50" />
              <p>No context available</p>
              <p className="text-xs mt-1">Context will appear after tool executions</p>
            </div>
          ) : (
            <div className="space-y-3">
              {/* Token usage summary */}
              <Card>
                <CardContent className="p-3">
                  <div className="flex items-center justify-between text-xs text-slate-500 mb-2">
                    <span>Token Usage</span>
                    <span>
                      {contextIndex.index_tokens.toLocaleString()} / {TOKEN_LIMIT.toLocaleString()}
                    </span>
                  </div>
                  <Progress
                    value={(contextIndex.index_tokens / TOKEN_LIMIT) * 100}
                    className="h-1.5"
                  />
                  <div className="flex justify-between text-[10px] text-slate-400 mt-1">
                    <span>Index: {contextIndex.index_tokens} tokens</span>
                    <span>Full: {contextIndex.full_tokens.toLocaleString()}</span>
                    <span>{Math.round(contextIndex.reduction_pct)}% reduction</span>
                  </div>
                </CardContent>
              </Card>

              {/* Context items */}
              <div className="space-y-2">
                {contextIndex.items.map((item) => {
                  const isExpanded = expandedContextIds.has(item.id);
                  const isExpanding = expandingIds.has(item.id);
                  const expandedContent = expandedContents.get(item.id);

                  return (
                    <Card
                      key={item.id}
                      className="overflow-hidden cursor-pointer"
                      onClick={() => expandContextItem(item.id)}
                    >
                      <CardHeader className="p-3 pb-2">
                        <div className="flex items-start justify-between gap-2">
                          <div className="flex items-center gap-2">
                            <Badge
                              variant="outline"
                              className={clsx("text-xs gap-1", getTypeColor(item.type))}
                            >
                              {getTypeIcon(item.type)}
                              {item.type}
                            </Badge>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-slate-500">
                            <span>~{item.token_estimate} tokens</span>
                            {isExpanding ? (
                              <Loader2 className="h-3.5 w-3.5 animate-spin" />
                            ) : isExpanded ? (
                              <ChevronUp className="h-3.5 w-3.5" />
                            ) : (
                              <ChevronDown className="h-3.5 w-3.5" />
                            )}
                          </div>
                        </div>
                        <CardTitle className="text-sm leading-tight mt-1.5">
                          {item.title}
                        </CardTitle>
                        {item.summary && (
                          <p className="text-xs text-slate-500 mt-0.5 line-clamp-2">
                            {item.summary}
                          </p>
                        )}
                      </CardHeader>

                      {isExpanded && expandedContent && (
                        <CardContent className="p-3 pt-0 border-t border-slate-200 dark:border-slate-800">
                          <div className="text-xs text-slate-400 mb-2">
                            Loaded {expandedContent.token_count} tokens
                          </div>
                          <pre className="text-xs text-slate-600 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/50 rounded p-2 overflow-x-auto whitespace-pre-wrap">
                            {JSON.stringify(expandedContent.content, null, 2)}
                          </pre>
                        </CardContent>
                      )}
                    </Card>
                  );
                })}
              </div>

              {/* Instructions */}
              {contextIndex.instructions && (
                <div className="text-xs text-slate-400 p-2 bg-slate-50 dark:bg-slate-800/50 rounded">
                  {contextIndex.instructions}
                </div>
              )}
            </div>
          )}
        </ScrollArea>
      )}
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
