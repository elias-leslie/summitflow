"use client";

import { useState, useEffect, useCallback } from "react";
import { clsx } from "clsx";
import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader } from "../ui/card";
import { ScrollArea } from "../ui/scroll-area";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../ui/select";
import {
  CheckCircle,
  XCircle,
  AlertCircle,
  MinusCircle,
  ChevronDown,
  ChevronUp,
  Clock,
  Cpu,
  FileCode,
  Sparkles,
} from "lucide-react";

interface DiaryViewerProps {
  projectId: string;
  className?: string;
  maxHeight?: string;
  showFilters?: boolean;
}

interface DiaryEntry {
  id: string;
  project_id: string;
  session_id: string;
  task_id: string | null;
  agent_type: string;
  duration_seconds: number | null;
  tokens_used: number | null;
  discovery_tokens: number | null;
  outcome: "success" | "failure" | "partial" | "neutral";
  observation_type: string | null;
  concepts: string[];
  what_worked: string[] | null;
  what_failed: string[] | null;
  user_corrections: string[] | null;
  patterns_used: string[] | null;
  reflected_at: string | null;
  reflection_notes: string | null;
  patterns_generated: string[] | null;
  created_at: string;
}

const OUTCOME_CONFIG = {
  success: {
    icon: CheckCircle,
    color: "bg-emerald-500/10 text-emerald-500 border-emerald-500/20",
    label: "Success",
  },
  failure: {
    icon: XCircle,
    color: "bg-red-500/10 text-red-500 border-red-500/20",
    label: "Failed",
  },
  partial: {
    icon: AlertCircle,
    color: "bg-amber-500/10 text-amber-500 border-amber-500/20",
    label: "Partial",
  },
  neutral: {
    icon: MinusCircle,
    color: "bg-gray-500/10 text-gray-500 border-gray-500/20",
    label: "Neutral",
  },
};

export function DiaryViewer({
  projectId,
  className,
  maxHeight = "500px",
  showFilters = true,
}: DiaryViewerProps) {
  const [entries, setEntries] = useState<DiaryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [outcomeFilter, setOutcomeFilter] = useState<string>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [unprocessedCount, setUnprocessedCount] = useState(0);

  const fetchEntries = useCallback(async () => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({ limit: "50" });
      if (outcomeFilter !== "all") {
        params.set("outcome", outcomeFilter);
      }

      const response = await fetch(
        `/api/projects/${projectId}/diary?${params}`
      );

      if (!response.ok) {
        throw new Error(`Failed to fetch diary entries: ${response.status}`);
      }

      const data = await response.json();
      setEntries(data.entries || []);
      setUnprocessedCount(data.unprocessed_count || 0);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load entries");
    } finally {
      setLoading(false);
    }
  }, [projectId, outcomeFilter]);

  useEffect(() => {
    fetchEntries();
  }, [fetchEntries]);

  const formatDuration = (seconds: number | null) => {
    if (!seconds) return null;
    if (seconds < 60) return `${seconds}s`;
    const mins = Math.floor(seconds / 60);
    const secs = seconds % 60;
    return `${mins}m ${secs}s`;
  };

  const formatTokens = (tokens: number | null) => {
    if (!tokens) return null;
    if (tokens >= 1000) return `${(tokens / 1000).toFixed(1)}k`;
    return tokens.toString();
  };

  const formatDate = (dateStr: string) => {
    return new Date(dateStr).toLocaleString();
  };

  const renderEntry = (entry: DiaryEntry) => {
    const config = OUTCOME_CONFIG[entry.outcome];
    const Icon = config.icon;
    const isExpanded = expandedId === entry.id;
    const isUnprocessed = !entry.reflected_at;

    return (
      <Card
        key={entry.id}
        className={clsx(
          "cursor-pointer transition-colors",
          isUnprocessed && "border-amber-500/30 bg-amber-500/5",
          isExpanded && "ring-1 ring-primary"
        )}
        onClick={() => setExpandedId(isExpanded ? null : entry.id)}
      >
        <CardHeader className="py-3 px-4">
          <div className="flex items-start justify-between gap-2">
            <div className="flex items-center gap-2 flex-wrap">
              <Badge variant="outline" className={clsx("gap-1", config.color)}>
                <Icon className="h-3 w-3" />
                {config.label}
              </Badge>
              <Badge variant="secondary" className="text-xs">
                {entry.agent_type}
              </Badge>
              {isUnprocessed && (
                <Badge
                  variant="outline"
                  className="bg-amber-500/10 text-amber-500 text-xs"
                >
                  <Sparkles className="h-3 w-3 mr-1" />
                  Pending reflection
                </Badge>
              )}
            </div>
            {isExpanded ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" />
            )}
          </div>

          {/* Concepts */}
          {entry.concepts && entry.concepts.length > 0 && (
            <div className="flex gap-1 flex-wrap mt-2">
              {entry.concepts.map((concept) => (
                <Badge key={concept} variant="secondary" className="text-xs">
                  {concept}
                </Badge>
              ))}
            </div>
          )}

          {/* Stats row */}
          <div className="flex gap-3 mt-2 text-xs text-muted-foreground">
            {entry.duration_seconds && (
              <span className="flex items-center gap-1">
                <Clock className="h-3 w-3" />
                {formatDuration(entry.duration_seconds)}
              </span>
            )}
            {entry.tokens_used && (
              <span className="flex items-center gap-1">
                <Cpu className="h-3 w-3" />
                {formatTokens(entry.tokens_used)} tokens
              </span>
            )}
            <span className="text-muted-foreground/60">
              {formatDate(entry.created_at)}
            </span>
          </div>
        </CardHeader>

        {/* Expanded content */}
        {isExpanded && (
          <CardContent className="pt-0 pb-3 px-4 space-y-3 border-t">
            {/* What worked */}
            {entry.what_worked && entry.what_worked.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-emerald-500 mb-1">
                  What Worked
                </h4>
                <ul className="text-sm space-y-1">
                  {(Array.isArray(entry.what_worked)
                    ? entry.what_worked
                    : JSON.parse(entry.what_worked as unknown as string)
                  ).map((item: string, i: number) => (
                    <li key={i} className="flex items-start gap-2">
                      <CheckCircle className="h-3 w-3 text-emerald-500 mt-1 shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* What failed */}
            {entry.what_failed && entry.what_failed.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-red-500 mb-1">
                  What Failed
                </h4>
                <ul className="text-sm space-y-1">
                  {(Array.isArray(entry.what_failed)
                    ? entry.what_failed
                    : JSON.parse(entry.what_failed as unknown as string)
                  ).map((item: string, i: number) => (
                    <li key={i} className="flex items-start gap-2">
                      <XCircle className="h-3 w-3 text-red-500 mt-1 shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* User corrections */}
            {entry.user_corrections && entry.user_corrections.length > 0 && (
              <div>
                <h4 className="text-xs font-medium text-amber-500 mb-1">
                  User Corrections
                </h4>
                <ul className="text-sm space-y-1">
                  {(Array.isArray(entry.user_corrections)
                    ? entry.user_corrections
                    : JSON.parse(entry.user_corrections as unknown as string)
                  ).map((item: string, i: number) => (
                    <li key={i} className="flex items-start gap-2">
                      <AlertCircle className="h-3 w-3 text-amber-500 mt-1 shrink-0" />
                      <span>{item}</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {/* Reflection notes */}
            {entry.reflection_notes && (
              <div>
                <h4 className="text-xs font-medium text-muted-foreground mb-1">
                  Reflection Notes
                </h4>
                <p className="text-sm text-muted-foreground">
                  {entry.reflection_notes}
                </p>
              </div>
            )}

            {/* Session ID */}
            <div className="text-xs text-muted-foreground flex items-center gap-1">
              <FileCode className="h-3 w-3" />
              Session: {entry.session_id.slice(0, 8)}...
            </div>
          </CardContent>
        )}
      </Card>
    );
  };

  return (
    <div className={className}>
      {/* Header with filters */}
      {showFilters && (
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <span className="text-sm font-medium">Diary Entries</span>
            {unprocessedCount > 0 && (
              <Badge variant="outline" className="bg-amber-500/10 text-amber-500">
                {unprocessedCount} pending reflection
              </Badge>
            )}
          </div>
          <Select value={outcomeFilter} onValueChange={setOutcomeFilter}>
            <SelectTrigger className="w-[140px] h-8">
              <SelectValue placeholder="Filter" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All outcomes</SelectItem>
              <SelectItem value="success">Success</SelectItem>
              <SelectItem value="partial">Partial</SelectItem>
              <SelectItem value="failure">Failed</SelectItem>
              <SelectItem value="neutral">Neutral</SelectItem>
            </SelectContent>
          </Select>
        </div>
      )}

      {/* Content */}
      {loading ? (
        <div className="flex items-center justify-center h-32 text-muted-foreground">
          Loading entries...
        </div>
      ) : error ? (
        <div className="flex items-center justify-center h-32 text-red-500">
          {error}
        </div>
      ) : entries.length === 0 ? (
        <div className="flex items-center justify-center h-32 text-muted-foreground">
          No diary entries yet
        </div>
      ) : (
        <ScrollArea className="pr-4" style={{ maxHeight }}>
          <div className="space-y-2">
            {entries.map(renderEntry)}
          </div>
        </ScrollArea>
      )}
    </div>
  );
}
