"use client";

import { Fragment, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  fetchVisionGoals,
  fetchVisionGoal,
  fetchVisionGoalDetails,
  fetchVisionContent,
  type VisionGoal,
  type VisionGoalDetail,
  type VisionContentResponse,
  type GoalDetail,
} from "@/lib/api";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  ChevronDown,
  ChevronRight,
  Target,
  Loader2,
  CheckCircle2,
  XCircle,
  HelpCircle,
  Compass,
  Shield,
  Lightbulb,
  Map,
  Check,
  Clock,
  Calendar,
} from "lucide-react";

interface VisionGoalsTabProps {
  projectId: string;
}

export function VisionGoalsTab({ projectId }: VisionGoalsTabProps) {
  const [expandedGoals, setExpandedGoals] = useState<Set<string>>(new Set());
  const [showPrinciples, setShowPrinciples] = useState(false);
  const [showRoadmap, setShowRoadmap] = useState(false);

  // Fetch all vision goals
  const { data: goalsData, isLoading: goalsLoading } = useQuery<VisionGoal[]>({
    queryKey: ["vision-goals", projectId],
    queryFn: () => fetchVisionGoals(projectId),
  });

  // Fetch vision content (mission, principles, roadmap)
  const { data: visionContent, isLoading: contentLoading } = useQuery<VisionContentResponse>({
    queryKey: ["vision-content", projectId],
    queryFn: () => fetchVisionContent(projectId),
  });

  // Toggle goal expansion
  const toggleGoal = (code: string) => {
    setExpandedGoals((prev) => {
      const next = new Set(prev);
      if (next.has(code)) {
        next.delete(code);
      } else {
        next.add(code);
      }
      return next;
    });
  };

  // Category color mapping - using Tailwind opacity modifiers
  const categoryColors: Record<string, string> = {
    Intelligence: "bg-green-500/10 text-green-400 border-green-500/30",
    Automation: "bg-violet-500/10 text-violet-400 border-violet-500/30",
    Experience: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
    Reliability: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    Transparency: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    Adaptability: "bg-pink-500/10 text-pink-400 border-pink-500/30",
    Integration: "bg-indigo-500/10 text-indigo-400 border-indigo-500/30",
    intelligence: "bg-green-500/10 text-green-400 border-green-500/30",
    automation: "bg-violet-500/10 text-violet-400 border-violet-500/30",
    experience: "bg-cyan-500/10 text-cyan-400 border-cyan-500/30",
    reliability: "bg-emerald-500/10 text-emerald-400 border-emerald-500/30",
    validation: "bg-amber-500/10 text-amber-400 border-amber-500/30",
    quality: "bg-pink-500/10 text-pink-400 border-pink-500/30",
    portfolio: "bg-indigo-500/10 text-indigo-400 border-indigo-500/30",
  };
  const defaultColor = "bg-zinc-500/10 text-zinc-400 border-zinc-500/30";

  // Get pass rate color class
  const getPassRateColorClass = (rate: number) => {
    if (rate >= 0.8) return "text-green-400";
    if (rate >= 0.5) return "text-yellow-400";
    if (rate > 0) return "text-orange-400";
    return "text-zinc-500";
  };

  // Get roadmap status icon
  const getRoadmapStatusIcon = (status: string) => {
    switch (status) {
      case "complete":
        return <Check className="h-4 w-4 text-green-400" />;
      case "in_progress":
        return <Clock className="h-4 w-4 text-yellow-400" />;
      case "planned":
        return <Calendar className="h-4 w-4 text-slate-500" />;
      default:
        return <Calendar className="h-4 w-4 text-slate-500" />;
    }
  };

  const isLoading = goalsLoading || contentLoading;

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="h-8 w-8 animate-spin text-slate-500" />
      </div>
    );
  }

  const goals = goalsData || [];
  const mission = visionContent?.content?.mission?.[0];
  const principles = visionContent?.content?.principle || [];
  const roadmapPhases = visionContent?.content?.roadmapPhase || [];

  // Calculate totals
  const totalFeatures = goals.reduce((sum, g) => sum + g.feature_count, 0);
  const totalCriteria = goals.reduce((sum, g) => sum + g.criteria_total, 0);
  const totalPassed = goals.reduce((sum, g) => sum + g.criteria_passed, 0);
  const overallPassRate = totalCriteria > 0 ? totalPassed / totalCriteria : 0;

  return (
    <div className="space-y-6">
      {/* Mission Statement */}
      {mission && (
        <div className="card border-phosphor-500/30 bg-phosphor-500/5 p-4">
          <div className="flex items-center gap-2 mb-2">
            <Compass className="h-5 w-5 text-phosphor-400" />
            <span className="font-semibold text-phosphor-400">{mission.title || "Mission Statement"}</span>
          </div>
          <p className="text-sm text-slate-400 leading-relaxed">
            {mission.content}
          </p>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-4 gap-4">
        <div className="card p-4">
          <div className="text-2xl font-bold text-white">{goals.length}</div>
          <div className="text-sm text-slate-500">Vision Goals</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-white">{totalFeatures}</div>
          <div className="text-sm text-slate-500">Linked Features</div>
        </div>
        <div className="card p-4">
          <div className="text-2xl font-bold text-white">{totalCriteria}</div>
          <div className="text-sm text-slate-500">Acceptance Criteria</div>
        </div>
        <div className="card p-4">
          <div
            className={`text-2xl font-bold ${getPassRateColorClass(overallPassRate)}`}
          >
            {Math.round(overallPassRate * 100)}%
          </div>
          <div className="text-sm text-slate-500">Overall Pass Rate</div>
        </div>
      </div>

      {/* Core Principles (Collapsible) */}
      {principles.length > 0 && (
        <div className="card">
          <button
            className="w-full flex items-center justify-between p-4 text-left"
            onClick={() => setShowPrinciples(!showPrinciples)}
          >
            <div className="flex items-center gap-2">
              <Shield className="h-5 w-5 text-blue-400" />
              <span className="font-semibold text-white">Core Principles</span>
              <Badge variant="slate" className="ml-2">{principles.length}</Badge>
            </div>
            {showPrinciples ? (
              <ChevronDown className="h-5 w-5 text-slate-500" />
            ) : (
              <ChevronRight className="h-5 w-5 text-slate-500" />
            )}
          </button>
          {showPrinciples && (
            <div className="px-4 pb-4 grid grid-cols-2 gap-3">
              {principles.map((p) => (
                <div
                  key={p.content_key}
                  className="rounded-lg border border-slate-700 bg-slate-800/50 p-3"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <Lightbulb className="h-4 w-4 text-yellow-400" />
                    <span className="font-medium text-sm text-white">{p.title}</span>
                  </div>
                  <p className="text-xs text-slate-400 line-clamp-3">
                    {p.content}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* Roadmap (Collapsible) */}
      {roadmapPhases.length > 0 && (
        <div className="card">
          <button
            className="w-full flex items-center justify-between p-4 text-left"
            onClick={() => setShowRoadmap(!showRoadmap)}
          >
            <div className="flex items-center gap-2">
              <Map className="h-5 w-5 text-green-400" />
              <span className="font-semibold text-white">Roadmap</span>
              <Badge variant="slate" className="ml-2">{roadmapPhases.length} phases</Badge>
            </div>
            {showRoadmap ? (
              <ChevronDown className="h-5 w-5 text-slate-500" />
            ) : (
              <ChevronRight className="h-5 w-5 text-slate-500" />
            )}
          </button>
          {showRoadmap && (
            <div className="px-4 pb-4 space-y-2">
              {roadmapPhases.map((phase) => {
                const status = (phase.metadata as { status?: string })?.status || "planned";
                const features = (phase.metadata as { features?: string[] })?.features || [];
                return (
                  <div
                    key={phase.content_key}
                    className="flex items-start gap-3 rounded-lg border border-slate-700 bg-slate-800/50 p-3"
                  >
                    <div className="shrink-0 mt-0.5">
                      {getRoadmapStatusIcon(status)}
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-sm text-white">{phase.title}</span>
                        <Badge
                          variant="outline"
                          className={
                            status === "complete"
                              ? "text-green-400 border-green-400/30"
                              : status === "in_progress"
                              ? "text-yellow-400 border-yellow-400/30"
                              : "text-slate-500"
                          }
                        >
                          {status.replace("_", " ")}
                        </Badge>
                      </div>
                      <p className="text-xs text-slate-400 mt-1">{phase.content}</p>
                      {features.length > 0 && (
                        <div className="flex flex-wrap gap-1 mt-2">
                          {features.map((f, i) => (
                            <span
                              key={i}
                              className="text-[10px] px-1.5 py-0.5 rounded bg-slate-700 text-slate-400"
                            >
                              {f}
                            </span>
                          ))}
                        </div>
                      )}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* Vision Goals Table */}
      {goals.length > 0 ? (
        <div className="card overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead className="px-2 w-28">Code</TableHead>
                <TableHead className="px-2 w-48">Name</TableHead>
                <TableHead className="px-2 w-28">Category</TableHead>
                <TableHead className="px-2 w-24 text-center">Features</TableHead>
                <TableHead className="px-2 w-24 text-center">Criteria</TableHead>
                <TableHead className="px-2 w-36">Pass Rate</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {goals.map((goal) => {
                const isExpanded = expandedGoals.has(goal.code);
                const colorClasses = goal.category
                  ? categoryColors[goal.category] || defaultColor
                  : defaultColor;

                return (
                  <Fragment key={goal.code}>
                    <TableRow
                      className="cursor-pointer hover:bg-slate-800/50"
                      onClick={() => toggleGoal(goal.code)}
                    >
                      <TableCell className="px-2 py-2">
                        <div className="flex items-center gap-1">
                          <span className="w-4 h-4 inline-flex items-center justify-center shrink-0">
                            {isExpanded ? (
                              <ChevronDown className="h-4 w-4 text-slate-500" />
                            ) : (
                              <ChevronRight className="h-4 w-4 text-slate-500" />
                            )}
                          </span>
                          <span className="mono text-xs text-phosphor-400">
                            {goal.code}
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="px-2 py-2">
                        <div className="flex items-center gap-2">
                          <Target className="h-4 w-4 text-slate-500 shrink-0" />
                          <span className="font-medium text-white">{goal.name}</span>
                        </div>
                      </TableCell>
                      <TableCell className="px-2 py-2">
                        {goal.category && (
                          <span
                            className={`text-xs px-1.5 py-0.5 rounded border ${colorClasses}`}
                          >
                            {goal.category}
                          </span>
                        )}
                      </TableCell>
                      <TableCell className="px-2 py-2 text-center">
                        <span className="text-sm text-slate-300">{goal.feature_count}</span>
                      </TableCell>
                      <TableCell className="px-2 py-2 text-center">
                        <span
                          className="text-sm mono"
                          style={{
                            color:
                              goal.criteria_passed === goal.criteria_total &&
                              goal.criteria_total > 0
                                ? "#4ade80"
                                : "#a1a1aa",
                          }}
                        >
                          {goal.criteria_passed}/{goal.criteria_total}
                        </span>
                      </TableCell>
                      <TableCell className="px-2 py-2">
                        <div className="flex items-center gap-2">
                          <Progress
                            value={goal.pass_rate * 100}
                            className="h-2 w-20"
                          />
                          <span
                            className={`text-xs font-medium ${getPassRateColorClass(goal.pass_rate)}`}
                          >
                            {Math.round(goal.pass_rate * 100)}%
                          </span>
                        </div>
                      </TableCell>
                    </TableRow>
                    {/* Expanded row showing linked features and goal details */}
                    {isExpanded && (
                      <TableRow className="bg-slate-800/30">
                        <TableCell colSpan={6} className="py-3 px-4">
                          <ExpandedGoalContent
                            projectId={projectId}
                            code={goal.code}
                            description={goal.description}
                          />
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="card p-8 text-center">
          <Target className="mx-auto h-12 w-12 text-slate-600" />
          <p className="mt-4 text-sm text-slate-500">
            No vision goals found. Run migration to populate goals from VISION.md.
          </p>
        </div>
      )}
    </div>
  );
}

// Sub-component to fetch and display goal details and linked features
function ExpandedGoalContent({
  projectId,
  code,
  description,
}: {
  projectId: string;
  code: string;
  description: string | null;
}) {
  const { data: goalDetail, isLoading: detailLoading } = useQuery<VisionGoalDetail>({
    queryKey: ["vision-goal", projectId, code],
    queryFn: () => fetchVisionGoal(projectId, code),
  });

  // Fetch goal details (objectives, features, success criteria)
  const { data: goalDetails } = useQuery<GoalDetail[]>({
    queryKey: ["vision-goal-details", projectId, code],
    queryFn: () => fetchVisionGoalDetails(projectId, code),
  });

  if (detailLoading) {
    return (
      <div className="flex items-center gap-2 text-sm text-slate-500">
        <Loader2 className="h-4 w-4 animate-spin" />
        Loading...
      </div>
    );
  }

  const features = goalDetail?.features || [];
  const objective = goalDetails?.find((d) => d.detail_type === "objective");
  const featureBullets = goalDetails?.filter((d) => d.detail_type === "feature") || [];
  const successCriteria = goalDetails?.filter((d) => d.detail_type === "success_criterion") || [];

  return (
    <div className="pl-6 space-y-4">
      {/* Description */}
      {description && (
        <p className="text-sm text-slate-400">{description}</p>
      )}

      {/* Objective */}
      {objective && (
        <div className="rounded-lg bg-phosphor-500/10 border border-phosphor-500/20 p-3">
          <div className="text-xs font-medium text-phosphor-400 mb-1">Objective</div>
          <p className="text-sm text-white">{objective.content}</p>
        </div>
      )}

      {/* Key Features from VISION.md */}
      {featureBullets.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2">Key Capabilities</div>
          <div className="space-y-1">
            {featureBullets.map((f) => {
              const highlight = (f.metadata as { highlight?: string })?.highlight;
              return (
                <div key={f.id} className="flex items-start gap-2 text-sm">
                  <CheckCircle2 className="h-4 w-4 text-green-400 shrink-0 mt-0.5" />
                  <span className="text-slate-300">
                    {highlight && <strong className="text-green-400">{highlight}:</strong>}{" "}
                    {f.content.replace(highlight ? `${highlight}: ` : "", "")}
                  </span>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Success Criteria */}
      {successCriteria.length > 0 && (
        <div>
          <div className="text-xs font-medium text-slate-500 mb-2">Success Criteria</div>
          <div className="space-y-1">
            {successCriteria.map((c) => (
              <div key={c.id} className="flex items-start gap-2 text-sm text-slate-400">
                <Target className="h-4 w-4 text-yellow-400 shrink-0 mt-0.5" />
                <span>{c.content}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Linked Features from DB */}
      <div>
        <div className="text-xs font-medium text-slate-500 mb-2">
          Linked Features ({features.length})
        </div>
        {features.length === 0 ? (
          <div className="text-sm text-slate-500">
            No features linked to this vision goal.
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-2">
            {features.map((f) => (
              <div
                key={f.feature_id}
                className="flex items-center gap-2 text-sm py-1 px-2 rounded bg-slate-800/50"
              >
                {f.criteria_total > 0 && f.criteria_passed === f.criteria_total ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-green-400 shrink-0" />
                ) : f.criteria_total > 0 && f.criteria_passed < f.criteria_total ? (
                  <XCircle className="h-3.5 w-3.5 text-red-400 shrink-0" />
                ) : (
                  <HelpCircle className="h-3.5 w-3.5 text-yellow-500 shrink-0" />
                )}
                <span className="mono text-xs text-slate-500 shrink-0">
                  {f.feature_id}
                </span>
                <span className="truncate flex-1 text-slate-300">{f.name}</span>
                {f.criteria_total > 0 && (
                  <span
                    className="text-xs mono shrink-0"
                    style={{
                      color:
                        f.criteria_passed === f.criteria_total
                          ? "#4ade80"
                          : f.criteria_passed > 0
                          ? "#facc15"
                          : "#71717a",
                    }}
                  >
                    {f.criteria_passed}/{f.criteria_total}
                  </span>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
