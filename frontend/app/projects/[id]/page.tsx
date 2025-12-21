"use client";

import { useState, useEffect } from "react";
import { useParams, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, AlertCircle, Clock, Globe, ListChecks, Target, Camera, ListTodo, Compass, Kanban, MessageCircle, Flag } from "lucide-react";
import Link from "next/link";
import {
  fetchProject,
  fetchProjectHealth,
  createRoundtableSession,
  getRoundtableSession,
  streamRoundtableMessage,
  generateFeaturesFromRoundtable,
  generateVisionFromRoundtable,
  generateGoalsFromRoundtable,
  saveVisionFromRoundtable,
  saveGoalsFromRoundtable,
  updateRoundtableTools,
  updateRoundtableAgentConfig,
  resolvePermission,
  type RoundtableMessage,
  type GeneratedFeature,
  type GeneratedMission,
  type GeneratedNarrative,
  type GeneratedGoal,
  type RoundtableSSEEvent,
  type ToolStats,
  type PermissionRequest,
} from "@/lib/api";
import { type AgentConfig } from "@/components/settings/AgentConfigPanel";
import { FeaturesTab } from "@/components/features/FeaturesTab";
import { VisionOverview } from "@/components/vision/VisionOverview";
import { TasksTab } from "@/components/tasks/TasksTab";
import { EvidenceTab } from "@/components/evidence/EvidenceTab";
import { GoalsList } from "@/components/goals/GoalsList";
import { ExplorerTab } from "@/components/explorer/ExplorerTab";
import { TaskKanbanBoard } from "@/components/kanban/TaskKanbanBoard";
import { TaskDetailDrawer } from "@/components/kanban/TaskDetailDrawer";
import {
  RoundtableChat,
  type ChatMessage,
  type RoundtableMode,
  type FileAttachment,
  type GeneratedVision,
} from "@/components/roundtable/RoundtableChat";
import { PermissionDialog } from "@/components/roundtable/PermissionDialog";
import { SessionList } from "@/components/roundtable/SessionList";
import { CreateTaskDialog } from "@/components/tasks/CreateTaskDialog";
import { fetchTasks, updateTaskStatus, type Task, type TaskStatus } from "@/lib/api";

type TabId = "roundtable" | "vision" | "goals" | "features" | "kanban" | "tasks" | "evidence" | "explorer";

export default function ProjectDetailPage() {
  const params = useParams();
  const searchParams = useSearchParams();
  const projectId = params.id as string;

  // Get initial tab from URL query param
  const urlTab = searchParams.get("tab") as TabId | null;
  const [activeTab, setActiveTab] = useState<TabId>(urlTab || "roundtable");

  // Sync with URL changes
  useEffect(() => {
    if (urlTab && ["roundtable", "vision", "goals", "features", "kanban", "tasks", "evidence", "explorer"].includes(urlTab)) {
      setActiveTab(urlTab);
    }
  }, [urlTab]);

  // Kanban state
  const [selectedTask, setSelectedTask] = useState<Task | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [createTaskDialogOpen, setCreateTaskDialogOpen] = useState(false);

  // Roundtable state
  const [roundtableSessionId, setRoundtableSessionId] = useState<string | null>(null);
  const [roundtableMode, setRoundtableMode] = useState<RoundtableMode>("spec_driven");
  const [roundtableMessages, setRoundtableMessages] = useState<ChatMessage[]>([]);
  const [roundtableLoading, setRoundtableLoading] = useState(false);
  const [streamingAgent, setStreamingAgent] = useState<"claude" | "gemini" | null>(null);
  const [roundtableError, setRoundtableError] = useState<string | null>(null);
  const [generatedFeatures, setGeneratedFeatures] = useState<GeneratedFeature[]>([]);
  const [roundtableSessionLoaded, setRoundtableSessionLoaded] = useState(false);
  const [toolsEnabled, setToolsEnabled] = useState(true);
  const [writeEnabled, setWriteEnabled] = useState(false);
  const [yoloMode, setYoloMode] = useState(false);
  const [toolStats, setToolStats] = useState<ToolStats>({ total_calls: 0, files_read: 0, searches: 0, writes: 0 });
  const [agentOverride, setAgentOverride] = useState<string | null>(null);
  const [modelOverride, setModelOverride] = useState<string | null>(null);

  // Permission prompting state
  const [pendingPermission, setPendingPermission] = useState<PermissionRequest | null>(null);
  const [permissionLoading, setPermissionLoading] = useState(false);

  // Load roundtable session from localStorage on mount
  useEffect(() => {
    const storageKey = `roundtable-session-${projectId}`;
    const savedSessionId = localStorage.getItem(storageKey);

    if (savedSessionId) {
      // Load session data from backend
      getRoundtableSession(projectId, savedSessionId)
        .then((session) => {
          setRoundtableSessionId(session.id);
          setRoundtableMode(session.mode as RoundtableMode);

          // Load tools settings
          setToolsEnabled(session.tools_enabled ?? true);
          setWriteEnabled(session.write_enabled ?? false);
          setYoloMode(session.yolo_mode ?? false);
          if (session.tool_stats) {
            setToolStats(session.tool_stats);
          }

          // Load agent config
          setAgentOverride(session.agent_override ?? null);
          setModelOverride(session.model_override ?? null);

          // Convert messages to ChatMessage format
          const messages: ChatMessage[] = session.messages.map((msg: RoundtableMessage) => ({
            id: msg.id,
            agent: msg.agent,
            content: msg.content,
            timestamp: new Date(msg.timestamp),
            tokensUsed: msg.tokens_used,
          }));
          setRoundtableMessages(messages);

          // Load generated features if any
          if (session.generated_features && session.generated_features.length > 0) {
            setGeneratedFeatures(session.generated_features);
          }
        })
        .catch((err) => {
          console.warn("Failed to load saved session:", err);
          // Clear invalid session
          localStorage.removeItem(storageKey);
        })
        .finally(() => {
          setRoundtableSessionLoaded(true);
        });
    } else {
      setRoundtableSessionLoaded(true);
    }
  }, [projectId]);

  // Save session ID to localStorage when it changes
  useEffect(() => {
    if (roundtableSessionId && roundtableSessionLoaded) {
      const storageKey = `roundtable-session-${projectId}`;
      localStorage.setItem(storageKey, roundtableSessionId);
    }
  }, [roundtableSessionId, projectId, roundtableSessionLoaded]);

  const { data: project, isLoading, error } = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
  });

  const { data: health } = useQuery({
    queryKey: ["project-health", projectId],
    queryFn: () => fetchProjectHealth(projectId),
    refetchInterval: 30000,
  });

  // Tasks for Kanban (fetch with feature context)
  const {
    data: kanbanTasksData,
    refetch: refetchKanbanTasks,
  } = useQuery({
    queryKey: ["tasks-kanban", projectId],
    queryFn: () => fetchTasks(projectId, { include: "feature", limit: 500 }),
    staleTime: 30000,
    enabled: activeTab === "kanban",
  });
  const kanbanTasks = kanbanTasksData?.tasks ?? [];

  // Kanban handlers
  const handleTaskStatusChange = async (taskId: string, newStatus: TaskStatus) => {
    try {
      await updateTaskStatus(projectId, taskId, newStatus);
      refetchKanbanTasks();
    } catch (err) {
      console.error("Failed to update task status:", err);
    }
  };

  const handleTaskClick = (task: Task) => {
    setSelectedTask(task);
    setDrawerOpen(true);
  };

  const handleNewTask = () => {
    setCreateTaskDialogOpen(true);
  };

  const handleCreateDialogChange = (open: boolean) => {
    setCreateTaskDialogOpen(open);
    if (!open) {
      // Refetch tasks when dialog closes (after create)
      refetchKanbanTasks();
    }
  };

  // Roundtable handlers
  const handleRoundtableModeChange = (mode: RoundtableMode) => {
    setRoundtableMode(mode);
  };

  const handleNewRoundtableSession = () => {
    // Clear current session
    setRoundtableSessionId(null);
    setRoundtableMessages([]);
    setGeneratedFeatures([]);
    setRoundtableError(null);
    // Reset tools state
    setToolsEnabled(true);
    setWriteEnabled(false);
    setYoloMode(false);
    setToolStats({ total_calls: 0, files_read: 0, searches: 0, writes: 0 });
    // Clear from localStorage
    const storageKey = `roundtable-session-${projectId}`;
    localStorage.removeItem(storageKey);
  };

  const handleSelectSession = async (sessionId: string) => {
    // Don't reload if already selected
    if (sessionId === roundtableSessionId) return;

    try {
      const session = await getRoundtableSession(projectId, sessionId);
      setRoundtableSessionId(session.id);
      setRoundtableMode(session.mode as RoundtableMode);

      // Load tools settings
      setToolsEnabled(session.tools_enabled ?? true);
      setWriteEnabled(session.write_enabled ?? false);
      setYoloMode(session.yolo_mode ?? false);
      if (session.tool_stats) {
        setToolStats(session.tool_stats);
      }

      // Load agent config
      setAgentOverride(session.agent_override ?? null);
      setModelOverride(session.model_override ?? null);

      // Convert messages to ChatMessage format
      const messages: ChatMessage[] = session.messages.map((msg: RoundtableMessage) => ({
        id: msg.id,
        agent: msg.agent,
        content: msg.content,
        timestamp: new Date(msg.timestamp),
        tokensUsed: msg.tokens_used,
      }));
      setRoundtableMessages(messages);

      // Load generated features if any
      if (session.generated_features && session.generated_features.length > 0) {
        setGeneratedFeatures(session.generated_features);
      } else {
        setGeneratedFeatures([]);
      }

      // Clear any errors
      setRoundtableError(null);

      // Save to localStorage for persistence
      const storageKey = `roundtable-session-${projectId}`;
      localStorage.setItem(storageKey, sessionId);
    } catch (err) {
      console.error("Failed to load session:", err);
      setRoundtableError("Failed to load session");
    }
  };

  const handleToolsChange = async (settings: { toolsEnabled?: boolean; writeEnabled?: boolean; yoloMode?: boolean }) => {
    // Optimistically update UI
    const prevToolsEnabled = toolsEnabled;
    const prevWriteEnabled = writeEnabled;
    const prevYoloMode = yoloMode;

    if (settings.toolsEnabled !== undefined) setToolsEnabled(settings.toolsEnabled);
    if (settings.writeEnabled !== undefined) setWriteEnabled(settings.writeEnabled);
    if (settings.yoloMode !== undefined) setYoloMode(settings.yoloMode);

    // If we have a session, persist the change
    if (roundtableSessionId) {
      try {
        const result = await updateRoundtableTools(projectId, roundtableSessionId, settings);
        setToolsEnabled(result.tools_enabled);
        setWriteEnabled(result.write_enabled);
        setYoloMode(result.yolo_mode);
        setToolStats(result.tool_stats);
      } catch (err) {
        // Revert on error
        setToolsEnabled(prevToolsEnabled);
        setWriteEnabled(prevWriteEnabled);
        setYoloMode(prevYoloMode);
        console.error("Failed to update tools settings:", err);
      }
    }
  };

  // Agent config handler
  const handleAgentConfigChange = async (config: AgentConfig) => {
    // Optimistically update UI
    const prevAgentOverride = agentOverride;
    const prevModelOverride = modelOverride;

    setAgentOverride(config.agentOverride);
    setModelOverride(config.modelOverride);

    // If we have a session, persist the change
    if (roundtableSessionId) {
      try {
        const result = await updateRoundtableAgentConfig(projectId, roundtableSessionId, {
          agent_override: config.agentOverride,
          model_override: config.modelOverride,
        });
        setAgentOverride(result.agent_override);
        setModelOverride(result.model_override);
      } catch (err) {
        // Revert on error
        setAgentOverride(prevAgentOverride);
        setModelOverride(prevModelOverride);
        console.error("Failed to update agent config:", err);
      }
    }
  };

  // Permission handlers
  const handleApprovePermission = async () => {
    if (!pendingPermission || !roundtableSessionId) return;
    setPermissionLoading(true);
    try {
      await resolvePermission(projectId, roundtableSessionId, pendingPermission.permission_id, true);
      setPendingPermission(null);
    } catch (error) {
      console.error("Failed to approve permission:", error);
    } finally {
      setPermissionLoading(false);
    }
  };

  const handleDenyPermission = async () => {
    if (!pendingPermission || !roundtableSessionId) return;
    setPermissionLoading(true);
    try {
      await resolvePermission(projectId, roundtableSessionId, pendingPermission.permission_id, false);
      setPendingPermission(null);
    } catch (error) {
      console.error("Failed to deny permission:", error);
    } finally {
      setPermissionLoading(false);
    }
  };

  const handleSendMessage = async (
    message: string,
    _attachments?: FileAttachment[],
    _targetAgent?: "claude" | "gemini" | "user"
  ) => {
    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      // Create session if needed
      let sessionId = roundtableSessionId;
      if (!sessionId) {
        const session = await createRoundtableSession(projectId, {
          mode: roundtableMode,
          toolsEnabled,
          writeEnabled,
          yoloMode,
        });
        sessionId = session.session_id;
        setRoundtableSessionId(sessionId);
        setToolsEnabled(session.tools_enabled);
        setWriteEnabled(session.write_enabled);
        setYoloMode(session.yolo_mode);
      }

      // Add user message to UI immediately
      const userMessage: ChatMessage = {
        id: `user-${Date.now()}`,
        agent: "user",
        content: message,
        timestamp: new Date(),
      };
      setRoundtableMessages((prev) => [...prev, userMessage]);

      // Stream responses via SSE
      const stream = streamRoundtableMessage(
        projectId,
        sessionId,
        message,
        "both" // Always send to both agents
      );

      for await (const event of stream) {
        switch (event.type) {
          case "agent_start":
            // Show which agent is typing
            if (event.data.agent) {
              setStreamingAgent(event.data.agent);
            }
            break;

          case "keepalive":
            // Keepalive ping to prevent connection timeout
            // Just ensures the streaming agent indicator stays visible
            console.debug(`Keepalive from ${event.data.agent}`);
            break;

          case "agent_complete":
            // Add agent response when complete
            if (event.data.id && event.data.agent && event.data.content) {
              const agentMessage: ChatMessage = {
                id: event.data.id,
                agent: event.data.agent,
                content: event.data.content,
                timestamp: event.data.timestamp ? new Date(event.data.timestamp) : new Date(),
                tokensUsed: event.data.tokens_used,
              };
              setRoundtableMessages((prev) => [...prev, agentMessage]);
            }
            setStreamingAgent(null);
            break;

          case "error":
            setRoundtableError(event.data.message || "An error occurred");
            break;

          case "permission_request":
            // Agent needs permission for a write operation
            if (event.data.permission_id && event.data.tool_name && event.data.agent) {
              setPendingPermission({
                permission_id: event.data.permission_id,
                tool_name: event.data.tool_name,
                params: event.data.params || {},
                preview: event.data.preview,
                agent: event.data.agent,
              });
            }
            break;

          case "done":
            // Stream complete
            break;
        }
      }
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to send message");
    } finally {
      setRoundtableLoading(false);
      setStreamingAgent(null);
    }
  };

  const handleGenerateFeatures = async (): Promise<GeneratedFeature[]> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return [];
    }

    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      const result = await generateFeaturesFromRoundtable(
        projectId,
        roundtableSessionId,
        "gemini" // Use Gemini for faster extraction
      );

      // Convert to the format expected by the component
      const features: GeneratedFeature[] = result.features.map((f) => ({
        feature_id: f.feature_id,
        name: f.name,
        category: f.category,
        priority: f.priority,
        description: f.description,
        acceptance_criteria: f.acceptance_criteria,
      }));

      setGeneratedFeatures(features);
      return features;
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to generate features");
      return [];
    } finally {
      setRoundtableLoading(false);
    }
  };

  const handleGenerateVision = async (): Promise<GeneratedVision> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return { mission: null, narratives: [] };
    }

    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      const result = await generateVisionFromRoundtable(
        projectId,
        roundtableSessionId,
        "claude"
      );

      return {
        mission: result.mission,
        narratives: result.narratives,
      };
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to generate vision");
      return { mission: null, narratives: [] };
    } finally {
      setRoundtableLoading(false);
    }
  };

  const handleGenerateGoals = async (): Promise<GeneratedGoal[]> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return [];
    }

    setRoundtableLoading(true);
    setRoundtableError(null);

    try {
      const result = await generateGoalsFromRoundtable(
        projectId,
        roundtableSessionId,
        "claude"
      );

      return result.goals;
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to generate goals");
      return [];
    } finally {
      setRoundtableLoading(false);
    }
  };

  const handleSaveVision = async (
    mission: GeneratedMission | null,
    narratives: GeneratedNarrative[]
  ): Promise<void> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return;
    }

    try {
      await saveVisionFromRoundtable(projectId, roundtableSessionId, mission, narratives);
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to save vision");
    }
  };

  const handleSaveGoals = async (goals: GeneratedGoal[]): Promise<void> => {
    if (!roundtableSessionId) {
      setRoundtableError("No active session");
      return;
    }

    try {
      await saveGoalsFromRoundtable(projectId, roundtableSessionId, goals);
    } catch (err) {
      setRoundtableError(err instanceof Error ? err.message : "Failed to save goals");
    }
  };

  if (isLoading) {
    return (
      <div className="p-6">
        <div className="flex items-center justify-center py-12">
          <div className="w-6 h-6 border-2 border-phosphor-500/30 border-t-phosphor-500 rounded-full animate-spin" />
        </div>
      </div>
    );
  }

  if (error || !project) {
    return (
      <div className="p-6">
        <div className="card p-8 text-center">
          <AlertCircle className="w-8 h-8 text-red-500 mx-auto mb-2" />
          <p className="text-slate-400">Failed to load project</p>
          <Link href="/" className="btn-secondary mt-4 inline-flex items-center gap-2">
            <ArrowLeft className="w-4 h-4" />
            Back to Dashboard
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <header className="animate-in">
        <Link
          href="/"
          className="text-xs text-slate-500 hover:text-phosphor-400 flex items-center gap-1 mb-3 transition-colors"
        >
          <ArrowLeft className="w-3 h-3" />
          Back to Dashboard
        </Link>

        <div className="flex items-start justify-between">
          <div className="flex items-center gap-4">
            <div className="w-14 h-14 rounded-xl bg-slate-800 flex items-center justify-center">
              <span className="display text-2xl font-bold text-phosphor-400">
                {project.name.charAt(0)}
              </span>
            </div>
            <div>
              <h1 className="display text-2xl font-semibold text-white">{project.name}</h1>
              <p className="mono text-sm text-slate-500">{project.id}</p>
            </div>
          </div>

          {/* Health status */}
          <div className="flex items-center gap-3">
            {health ? (
              <>
                <div
                  className={`status-dot ${health.healthy ? "healthy" : "error"}`}
                />
                <span className="text-sm text-slate-400">
                  {health.healthy ? "Healthy" : "Unhealthy"}
                </span>
                {health.response_time_ms && (
                  <span className="mono text-xs text-slate-500 tabular-nums">
                    {Math.round(health.response_time_ms)}ms
                  </span>
                )}
              </>
            ) : (
              <div className="status-dot unknown" />
            )}
          </div>
        </div>

        {/* Project info */}
        <div className="mt-4 flex items-center gap-6 text-sm text-slate-400">
          <span className="flex items-center gap-2">
            <Globe className="w-4 h-4" />
            <span className="mono">{project.base_url}</span>
          </span>
          <span className="flex items-center gap-2">
            <Clock className="w-4 h-4" />
            Created {new Date(project.created_at).toLocaleDateString()}
          </span>
        </div>
      </header>

      {/* Tab Navigation */}
      <nav className="border-b border-slate-700">
        <div className="flex gap-1">
          <button
            onClick={() => setActiveTab("roundtable")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "roundtable"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <MessageCircle className="w-4 h-4" />
              Roundtable
            </div>
            {activeTab === "roundtable" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("vision")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "vision"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Target className="w-4 h-4" />
              Vision
            </div>
            {activeTab === "vision" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("goals")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "goals"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Flag className="w-4 h-4" />
              Goals
            </div>
            {activeTab === "goals" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("features")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "features"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <ListChecks className="w-4 h-4" />
              Features
            </div>
            {activeTab === "features" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("kanban")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "kanban"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Kanban className="w-4 h-4" />
              Kanban
            </div>
            {activeTab === "kanban" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("tasks")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "tasks"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <ListTodo className="w-4 h-4" />
              Tasks
            </div>
            {activeTab === "tasks" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("evidence")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "evidence"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Camera className="w-4 h-4" />
              Evidence
            </div>
            {activeTab === "evidence" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
          <button
            onClick={() => setActiveTab("explorer")}
            className={`px-4 py-2.5 text-sm font-medium transition-colors relative ${
              activeTab === "explorer"
                ? "text-phosphor-400"
                : "text-slate-500 hover:text-slate-300"
            }`}
          >
            <div className="flex items-center gap-2">
              <Compass className="w-4 h-4" />
              Explorer
            </div>
            {activeTab === "explorer" && (
              <div className="absolute bottom-0 left-0 right-0 h-0.5 bg-phosphor-500" />
            )}
          </button>
        </div>
      </nav>

      {/* Tab Content */}
      <section className="animate-fade-in">
        {activeTab === "roundtable" && (
          <div className="flex gap-4">
            {/* Session List Panel */}
            <div className="w-72 flex-shrink-0">
              <SessionList
                projectId={projectId}
                currentSessionId={roundtableSessionId ?? undefined}
                onSelectSession={handleSelectSession}
                onNewSession={handleNewRoundtableSession}
              />
            </div>

            {/* Chat Panel */}
            <RoundtableChat
              projectId={projectId}
              sessionId={roundtableSessionId ?? undefined}
              className="flex-1 h-[calc(100vh-320px)] min-h-[500px]"
              mode={roundtableMode}
              onModeChange={handleRoundtableModeChange}
              onSendMessage={handleSendMessage}
              onGenerateFeatures={handleGenerateFeatures}
              onGenerateVision={handleGenerateVision}
              onGenerateGoals={handleGenerateGoals}
              onSaveVision={handleSaveVision}
              onSaveGoals={handleSaveGoals}
              onNewSession={handleNewRoundtableSession}
              messages={roundtableMessages}
              isLoading={roundtableLoading}
              streamingAgent={streamingAgent}
              connected={true}
              error={roundtableError}
              toolsEnabled={toolsEnabled}
              writeEnabled={writeEnabled}
              yoloMode={yoloMode}
              toolStats={toolStats}
              onToolsChange={handleToolsChange}
              agentOverride={agentOverride}
              modelOverride={modelOverride}
              onAgentConfigChange={handleAgentConfigChange}
            />
          </div>
        )}
        {activeTab === "vision" && <VisionOverview projectId={projectId} />}
        {activeTab === "goals" && <GoalsList projectId={projectId} />}
        {activeTab === "features" && <FeaturesTab projectId={projectId} />}
        {activeTab === "kanban" && (
          <>
            <TaskKanbanBoard
              tasks={kanbanTasks}
              projectId={projectId}
              onStatusChange={handleTaskStatusChange}
              onTaskClick={handleTaskClick}
              onNewTask={handleNewTask}
            />
            <TaskDetailDrawer
              task={selectedTask}
              projectId={projectId}
              open={drawerOpen}
              onOpenChange={setDrawerOpen}
              onStatusChange={handleTaskStatusChange}
            />
            <CreateTaskDialog
              open={createTaskDialogOpen}
              onOpenChange={handleCreateDialogChange}
              projectId={projectId}
            />
          </>
        )}
        {activeTab === "tasks" && <TasksTab projectId={projectId} />}
        {activeTab === "evidence" && <EvidenceTab projectId={projectId} />}
        {activeTab === "explorer" && <ExplorerTab projectId={projectId} />}
      </section>

      {/* Permission Dialog for write tool approval */}
      <PermissionDialog
        open={!!pendingPermission}
        request={pendingPermission}
        onApprove={handleApprovePermission}
        onDeny={handleDenyPermission}
        isLoading={permissionLoading}
      />
    </div>
  );
}
