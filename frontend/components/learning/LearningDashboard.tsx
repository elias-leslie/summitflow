"use client";

import { useState, useEffect, useCallback } from "react";
import { clsx } from "clsx";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Switch } from "../ui/switch";
import { Label } from "../ui/label";
import {
  Sparkles,
  Clock,
  CheckCircle,
  AlertTriangle,
  RefreshCw,
  Settings,
  BookOpen,
} from "lucide-react";
import { PatternCard } from "./PatternCard";
import { DiaryViewer } from "./DiaryViewer";

interface LearningDashboardProps {
  projectId: string;
  projectPath?: string;
  className?: string;
}

interface Pattern {
  id: string;
  project_id: string;
  pattern_type: string;
  title: string;
  content: string;
  rationale: string | null;
  source_diary_ids: string[] | null;
  source_observation_ids: string[] | null;
  action: "add" | "update" | "remove" | "merge";
  target_pattern_id: string | null;
  status: "pending" | "approved" | "applied" | "rejected" | "merged";
  confidence: number | null;
  usage_count: number | null;
  last_used_at: string | null;
  applied_to_rules_at: string | null;
  created_at: string | null;
}

interface PatternCounts {
  pending: number;
  approved: number;
  applied: number;
}

export function LearningDashboard({
  projectId,
  projectPath,
  className,
}: LearningDashboardProps) {
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [stalePatterns, setStalePatterns] = useState<Pattern[]>([]);
  const [counts, setCounts] = useState<PatternCounts>({
    pending: 0,
    approved: 0,
    applied: 0,
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState("pending");
  const [triggeringReflection, setTriggeringReflection] = useState(false);
  const [autoApply, setAutoApply] = useState(true);
  const [showSettings, setShowSettings] = useState(false);

  const fetchPatterns = useCallback(async (status?: string) => {
    setLoading(true);
    setError(null);

    try {
      const params = new URLSearchParams({ limit: "100" });
      if (status && status !== "all") {
        params.set("status", status);
      }

      const response = await fetch(
        `/api/projects/${projectId}/patterns?${params}`
      );

      if (!response.ok) {
        throw new Error(`Failed to fetch patterns: ${response.status}`);
      }

      const data = await response.json();
      setPatterns(data.patterns || []);
      setCounts(data.counts || { pending: 0, approved: 0, applied: 0 });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load patterns");
    } finally {
      setLoading(false);
    }
  }, [projectId]);

  const fetchStalePatterns = useCallback(async () => {
    try {
      const response = await fetch(
        `/api/projects/${projectId}/patterns/stale?days=30`
      );

      if (response.ok) {
        const data = await response.json();
        setStalePatterns(data.stale_patterns || []);
      }
    } catch (err) {
      console.error("Failed to fetch stale patterns:", err);
    }
  }, [projectId]);

  useEffect(() => {
    fetchPatterns();
    fetchStalePatterns();
  }, [fetchPatterns, fetchStalePatterns]);

  const handleApprove = async (patternId: string) => {
    const response = await fetch(
      `/api/projects/${projectId}/patterns/${patternId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "approved" }),
      }
    );

    if (response.ok) {
      fetchPatterns();
    }
  };

  const handleReject = async (patternId: string) => {
    const response = await fetch(
      `/api/projects/${projectId}/patterns/${patternId}`,
      {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ status: "rejected" }),
      }
    );

    if (response.ok) {
      fetchPatterns();
    }
  };

  const handleApply = async (patternId: string) => {
    if (!projectPath) {
      alert("Project path required to apply patterns");
      return;
    }

    const response = await fetch(
      `/api/projects/${projectId}/patterns/${patternId}/apply?project_path=${encodeURIComponent(projectPath)}`,
      { method: "POST" }
    );

    if (response.ok) {
      fetchPatterns();
    }
  };

  const handleUndo = async (patternId: string) => {
    const response = await fetch(
      `/api/projects/${projectId}/patterns/${patternId}/undo`,
      { method: "POST" }
    );

    if (response.ok) {
      fetchPatterns();
    }
  };

  const handleTriggerReflection = async () => {
    setTriggeringReflection(true);

    try {
      const params = projectPath
        ? `?project_path=${encodeURIComponent(projectPath)}`
        : "";

      const response = await fetch(
        `/api/projects/${projectId}/reflection/trigger${params}`,
        {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ auto_apply: autoApply }),
        }
      );

      if (response.ok) {
        const data = await response.json();
        // Refresh patterns after reflection
        fetchPatterns();
        alert(
          `Reflection complete: ${data.patterns_created?.length || 0} patterns created`
        );
      }
    } catch (err) {
      console.error("Reflection failed:", err);
    } finally {
      setTriggeringReflection(false);
    }
  };

  const getFilteredPatterns = (status: string) => {
    if (status === "stale") return stalePatterns;
    return patterns.filter((p) => p.status === status);
  };

  return (
    <div className={clsx("space-y-6", className)}>
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <Sparkles className="h-5 w-5 text-primary" />
          <h2 className="text-lg font-semibold">Learning System</h2>
        </div>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowSettings(!showSettings)}
          >
            <Settings className="h-4 w-4 mr-1" />
            Settings
          </Button>
          <Button
            size="sm"
            onClick={handleTriggerReflection}
            disabled={triggeringReflection}
          >
            <RefreshCw
              className={clsx("h-4 w-4 mr-1", triggeringReflection && "animate-spin")}
            />
            {triggeringReflection ? "Analyzing..." : "Analyze Recent Work"}
          </Button>
        </div>
      </div>

      {/* Settings panel */}
      {showSettings && (
        <Card>
          <CardHeader className="py-3">
            <CardTitle className="text-sm">Reflection Settings</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <Label htmlFor="auto-apply" className="text-sm">
                Auto-apply high-confidence patterns
              </Label>
              <Switch
                id="auto-apply"
                checked={autoApply}
                onCheckedChange={setAutoApply}
              />
            </div>
            <p className="text-xs text-muted-foreground">
              Patterns with 90%+ confidence will be automatically applied to
              .claude/rules/ without manual review.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Error state */}
      {error && (
        <div className="p-4 bg-red-500/10 text-red-500 rounded-md text-sm">
          {error}
        </div>
      )}

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList className="grid w-full grid-cols-5">
          <TabsTrigger value="pending" className="gap-1">
            <Clock className="h-3 w-3" />
            Pending
            {counts.pending > 0 && (
              <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                {counts.pending}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="approved" className="gap-1">
            <CheckCircle className="h-3 w-3" />
            Approved
            {counts.approved > 0 && (
              <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                {counts.approved}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="applied" className="gap-1">
            <Sparkles className="h-3 w-3" />
            Applied
            {counts.applied > 0 && (
              <Badge variant="secondary" className="ml-1 h-5 px-1.5">
                {counts.applied}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="stale" className="gap-1">
            <AlertTriangle className="h-3 w-3" />
            Stale
            {stalePatterns.length > 0 && (
              <Badge
                variant="secondary"
                className="ml-1 h-5 px-1.5 bg-amber-500/20 text-amber-500"
              >
                {stalePatterns.length}
              </Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="diary" className="gap-1">
            <BookOpen className="h-3 w-3" />
            Diary
          </TabsTrigger>
        </TabsList>

        {/* Pending patterns */}
        <TabsContent value="pending" className="mt-4">
          {loading ? (
            <div className="text-center py-8 text-muted-foreground">
              Loading patterns...
            </div>
          ) : getFilteredPatterns("pending").length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No pending patterns. Run reflection to analyze recent work.
            </div>
          ) : (
            <div className="space-y-3">
              {getFilteredPatterns("pending").map((pattern) => (
                <PatternCard
                  key={pattern.id}
                  pattern={pattern}
                  projectPath={projectPath}
                  onApprove={handleApprove}
                  onReject={handleReject}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Approved patterns */}
        <TabsContent value="approved" className="mt-4">
          {getFilteredPatterns("approved").length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No approved patterns waiting to be applied.
            </div>
          ) : (
            <div className="space-y-3">
              {getFilteredPatterns("approved").map((pattern) => (
                <PatternCard
                  key={pattern.id}
                  pattern={pattern}
                  projectPath={projectPath}
                  onApply={handleApply}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Applied patterns */}
        <TabsContent value="applied" className="mt-4">
          {getFilteredPatterns("applied").length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No patterns have been applied yet.
            </div>
          ) : (
            <div className="space-y-3">
              {getFilteredPatterns("applied").map((pattern) => (
                <PatternCard
                  key={pattern.id}
                  pattern={pattern}
                  projectPath={projectPath}
                  onUndo={handleUndo}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Stale patterns */}
        <TabsContent value="stale" className="mt-4">
          {stalePatterns.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              No stale patterns. All applied patterns are being used.
            </div>
          ) : (
            <div className="space-y-3">
              <div className="text-sm text-muted-foreground mb-4">
                These patterns haven&apos;t been used in the last 30 days. Consider
                removing them.
              </div>
              {stalePatterns.map((pattern) => (
                <PatternCard
                  key={pattern.id}
                  pattern={pattern}
                  projectPath={projectPath}
                  onUndo={handleUndo}
                />
              ))}
            </div>
          )}
        </TabsContent>

        {/* Diary viewer */}
        <TabsContent value="diary" className="mt-4">
          <DiaryViewer projectId={projectId} maxHeight="600px" />
        </TabsContent>
      </Tabs>
    </div>
  );
}
