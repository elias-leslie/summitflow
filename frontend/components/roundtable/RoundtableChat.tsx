"use client";

import {
  useEffect,
  useRef,
  useState,
  useCallback,
  FormEvent,
  DragEvent,
  ClipboardEvent,
  ChangeEvent,
} from "react";
import { clsx } from "clsx";
import { ScrollArea } from "../ui/scroll-area";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import {
  Send,
  Loader2,
  User,
  Sparkles,
  Bot,
  WifiOff,
  CircleDot,
  Paperclip,
  X,
  FileText,
  Image as ImageIcon,
  File,
  Wand2,
  Zap,
  CheckCircle,
  ListChecks,
  Plus,
  FolderCode,
  Eye,
  Target,
  ChevronDown,
} from "lucide-react";
import { VisionPreview, GeneratedMission, GeneratedNarrative } from "./VisionPreview";
import { GoalsPreview, GeneratedGoal } from "./GoalsPreview";
import { SpecPreview, GeneratedSpec, SpecComponent, SpecCapability, SpecTest } from "./SpecPreview";

// Re-export spec types for consumers
export type { GeneratedSpec, SpecComponent, SpecCapability, SpecTest };
import { Switch } from "../ui/switch";
import { Layers } from "lucide-react";
import { AgentConfigPanel, AgentConfig } from "../settings/AgentConfigPanel";

export type AgentType = "claude" | "gemini" | "user";
export type RoundtableMode = "spec_driven" | "quick";

export interface FileAttachment {
  id: string;
  file: File;
  previewUrl?: string;
  type: "image" | "document" | "other";
}

export interface ChatMessage {
  id: string;
  agent: AgentType;
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  tokensUsed?: number;
  attachments?: FileAttachment[];
}

export interface GeneratedFeature {
  capability_id: string;
  name: string;
  category: string;
  priority: number;
  acceptance_criteria: { id: string; description: string }[];
}

export interface ToolStats {
  total_calls: number;
  files_read: number;
  searches: number;
  writes: number;
}

export interface ToolsSettings {
  toolsEnabled: boolean;
  writeEnabled: boolean;
  yoloMode: boolean;
}

export interface GeneratedVision {
  mission: GeneratedMission | null;
  narratives: GeneratedNarrative[];
}

interface RoundtableChatProps {
  projectId: string;
  sessionId?: string;
  className?: string;
  mode?: RoundtableMode;
  onModeChange?: (mode: RoundtableMode) => void;
  onSendMessage?: (
    message: string,
    attachments?: FileAttachment[],
    targetAgent?: AgentType
  ) => Promise<void>;
  onGenerateFeatures?: () => Promise<GeneratedFeature[]>;
  onGenerateVision?: () => Promise<GeneratedVision>;
  onGenerateGoals?: () => Promise<GeneratedGoal[]>;
  onGenerateSpec?: () => Promise<GeneratedSpec>;
  onSaveVision?: (mission: GeneratedMission | null, narratives: GeneratedNarrative[]) => Promise<void>;
  onSaveGoals?: (goals: GeneratedGoal[]) => Promise<void>;
  onAcceptSpec?: () => Promise<void>;
  onNewSession?: () => void;
  // External spec (fetched from API)
  generatedSpec?: GeneratedSpec | null;
  messages?: ChatMessage[];
  isLoading?: boolean;
  streamingAgent?: "claude" | "gemini" | null;
  connected?: boolean;
  error?: string | null;
  // Tools/codebase access props
  toolsEnabled?: boolean;
  writeEnabled?: boolean;
  yoloMode?: boolean;
  toolStats?: ToolStats;
  onToolsChange?: (settings: Partial<ToolsSettings>) => void;
  // Agent configuration props
  agentOverride?: string | null;
  modelOverride?: string | null;
  onAgentConfigChange?: (config: AgentConfig) => void;
}

// Agent styling configuration
const agentConfig: Record<
  AgentType,
  {
    name: string;
    icon: typeof User;
    bgColor: string;
    textColor: string;
    borderColor: string;
    iconBg: string;
  }
> = {
  user: {
    name: "You",
    icon: User,
    bgColor: "bg-slate-800/50",
    textColor: "text-slate-200",
    borderColor: "border-slate-700",
    iconBg: "bg-slate-700",
  },
  claude: {
    name: "Claude",
    icon: Sparkles,
    bgColor: "bg-amber-950/30",
    textColor: "text-amber-200",
    borderColor: "border-amber-900/50",
    iconBg: "bg-amber-900/50",
  },
  gemini: {
    name: "Gemini",
    icon: Bot,
    bgColor: "bg-blue-950/30",
    textColor: "text-blue-200",
    borderColor: "border-blue-900/50",
    iconBg: "bg-blue-900/50",
  },
};

function getFileType(file: File): "image" | "document" | "other" {
  if (file.type.startsWith("image/")) return "image";
  if (
    file.type.includes("pdf") ||
    file.type.includes("text") ||
    file.type.includes("document") ||
    file.name.endsWith(".md") ||
    file.name.endsWith(".txt") ||
    file.name.endsWith(".json")
  )
    return "document";
  return "other";
}

function FilePreview({
  attachment,
  onRemove,
}: {
  attachment: FileAttachment;
  onRemove: () => void;
}) {
  const Icon =
    attachment.type === "image"
      ? ImageIcon
      : attachment.type === "document"
        ? FileText
        : File;

  return (
    <div className="relative group flex-shrink-0">
      {attachment.type === "image" && attachment.previewUrl ? (
        <div className="w-16 h-16 rounded-lg overflow-hidden border border-slate-600">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            src={attachment.previewUrl}
            alt={attachment.file.name}
            className="w-full h-full object-cover"
          />
        </div>
      ) : (
        <div className="w-16 h-16 rounded-lg bg-slate-700 border border-slate-600 flex flex-col items-center justify-center gap-1">
          <Icon className="w-5 h-5 text-slate-400" />
          <span className="text-2xs text-slate-400 truncate max-w-[56px] px-1">
            {attachment.file.name.split(".").pop()?.toUpperCase()}
          </span>
        </div>
      )}
      <button
        type="button"
        onClick={onRemove}
        className="absolute -top-1.5 -right-1.5 w-5 h-5 rounded-full bg-rose-500 text-white flex items-center justify-center opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <X className="w-3 h-3" />
      </button>
      <span className="absolute -bottom-5 left-0 right-0 text-2xs text-slate-500 truncate text-center">
        {attachment.file.name}
      </span>
    </div>
  );
}

function MessageAttachments({
  attachments,
}: {
  attachments: FileAttachment[];
}) {
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {attachments.map((attachment) => (
        <div key={attachment.id} className="flex-shrink-0">
          {attachment.type === "image" && attachment.previewUrl ? (
            <div className="w-24 h-24 rounded-lg overflow-hidden border border-slate-600">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                src={attachment.previewUrl}
                alt={attachment.file.name}
                className="w-full h-full object-cover"
              />
            </div>
          ) : (
            <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-slate-700/50 border border-slate-600">
              <FileText className="w-4 h-4 text-slate-400" />
              <span className="text-xs text-slate-300">{attachment.file.name}</span>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function MessageBubble({
  message,
  isLast,
}: {
  message: ChatMessage;
  isLast: boolean;
}) {
  const config = agentConfig[message.agent];
  const Icon = config.icon;
  const isUser = message.agent === "user";

  return (
    <div
      className={clsx(
        "flex gap-3 p-4 rounded-lg border",
        config.bgColor,
        config.borderColor,
        isUser && "flex-row-reverse"
      )}
    >
      {/* Avatar */}
      <div
        className={clsx(
          "flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center",
          config.iconBg
        )}
      >
        <Icon className={clsx("w-4 h-4", config.textColor)} />
      </div>

      {/* Content */}
      <div className={clsx("flex-1 min-w-0", isUser && "text-right")}>
        {/* Header */}
        <div
          className={clsx(
            "flex items-center gap-2 mb-1",
            isUser && "justify-end"
          )}
        >
          <span className={clsx("text-sm font-medium", config.textColor)}>
            {config.name}
          </span>
          <span className="text-xs text-slate-500">
            {message.timestamp.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
          {message.tokensUsed && message.tokensUsed > 0 && (
            <span className="text-xs text-slate-500 mono">
              {message.tokensUsed.toLocaleString()} tokens
            </span>
          )}
        </div>

        {/* Message content */}
        <div
          className={clsx(
            "text-sm whitespace-pre-wrap break-words",
            config.textColor
          )}
        >
          {message.content}
          {message.isStreaming && isLast && (
            <span className="inline-block w-2 h-4 bg-current animate-pulse ml-0.5" />
          )}
        </div>

        {/* Attachments */}
        {message.attachments && message.attachments.length > 0 && (
          <MessageAttachments attachments={message.attachments} />
        )}
      </div>
    </div>
  );
}

function ModeSelector({
  mode,
  onModeChange,
  disabled,
}: {
  mode: RoundtableMode;
  onModeChange?: (mode: RoundtableMode) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex rounded-lg bg-slate-800 p-1 gap-1">
      <button
        type="button"
        onClick={() => onModeChange?.("spec_driven")}
        disabled={disabled}
        className={clsx(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
          mode === "spec_driven"
            ? "bg-phosphor-500 text-white"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
        )}
      >
        <Wand2 className="w-3.5 h-3.5" />
        Spec-Driven
      </button>
      <button
        type="button"
        onClick={() => onModeChange?.("quick")}
        disabled={disabled}
        className={clsx(
          "flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium transition-colors",
          mode === "quick"
            ? "bg-phosphor-500 text-white"
            : "text-slate-400 hover:text-slate-200 hover:bg-slate-700"
        )}
      >
        <Zap className="w-3.5 h-3.5" />
        Quick
      </button>
    </div>
  );
}

function GeneratedFeaturesList({
  features,
  onClose,
}: {
  features: GeneratedFeature[];
  onClose: () => void;
}) {
  return (
    <div className="p-4 bg-phosphor-950/50 border border-phosphor-900 rounded-lg">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <CheckCircle className="w-5 h-5 text-phosphor-400" />
          <h4 className="text-sm font-medium text-phosphor-200">
            {features.length} Feature{features.length !== 1 ? "s" : ""} Generated
          </h4>
        </div>
        <button
          onClick={onClose}
          className="text-slate-400 hover:text-slate-200"
        >
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="space-y-2">
        {features.map((feat) => (
          <div
            key={feat.capability_id}
            className="flex items-start gap-3 p-3 bg-slate-800/50 rounded-lg"
          >
            <ListChecks className="w-4 h-4 text-phosphor-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 mono">{feat.capability_id}</span>
                <Badge variant="phosphor" className="text-2xs">
                  P{feat.priority}
                </Badge>
                <Badge variant="slate" className="text-2xs">
                  {feat.category}
                </Badge>
              </div>
              <p className="text-sm text-slate-200 mt-1">{feat.name}</p>
              <p className="text-xs text-slate-500 mt-0.5">
                {feat.acceptance_criteria.length} criteria
              </p>
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500 mt-3">
        Features added to your Kanban board in backlog.
      </p>
    </div>
  );
}

export function RoundtableChat({
  projectId,
  sessionId,
  className,
  mode = "quick",
  onModeChange,
  onSendMessage,
  onGenerateFeatures,
  onGenerateVision,
  onGenerateGoals,
  onGenerateSpec,
  onSaveVision,
  onSaveGoals,
  onAcceptSpec,
  onNewSession,
  generatedSpec = null,
  messages = [],
  isLoading = false,
  streamingAgent = null,
  connected = true,
  error = null,
  toolsEnabled = true,
  writeEnabled = false,
  yoloMode = false,
  toolStats,
  onToolsChange,
  agentOverride = null,
  modelOverride = null,
  onAgentConfigChange,
}: RoundtableChatProps) {
  const [inputValue, setInputValue] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [isGeneratingVision, setIsGeneratingVision] = useState(false);
  const [isGeneratingGoals, setIsGeneratingGoals] = useState(false);
  const [isGeneratingSpec, setIsGeneratingSpec] = useState(false);
  const [showSpecPreview, setShowSpecPreview] = useState(true);
  const [attachments, setAttachments] = useState<FileAttachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [generatedFeatures, setGeneratedFeatures] = useState<GeneratedFeature[]>([]);
  const [generatedVision, setGeneratedVision] = useState<GeneratedVision | null>(null);
  const [generatedGoals, setGeneratedGoals] = useState<GeneratedGoal[]>([]);
  const [showGenerateMenu, setShowGenerateMenu] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  // Cleanup preview URLs on unmount or attachment change
  useEffect(() => {
    return () => {
      attachments.forEach((att) => {
        if (att.previewUrl) {
          URL.revokeObjectURL(att.previewUrl);
        }
      });
    };
  }, [attachments]);

  const addFiles = useCallback((files: FileList | File[]) => {
    const newAttachments: FileAttachment[] = Array.from(files).map((file) => {
      const type = getFileType(file);
      const previewUrl = type === "image" ? URL.createObjectURL(file) : undefined;
      return {
        id: crypto.randomUUID(),
        file,
        type,
        previewUrl,
      };
    });
    setAttachments((prev) => [...prev, ...newAttachments]);
  }, []);

  const removeAttachment = useCallback((id: string) => {
    setAttachments((prev) => {
      const att = prev.find((a) => a.id === id);
      if (att?.previewUrl) {
        URL.revokeObjectURL(att.previewUrl);
      }
      return prev.filter((a) => a.id !== id);
    });
  }, []);

  const handleDragOver = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  }, []);

  const handleDragLeave = useCallback((e: DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(false);
  }, []);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      e.stopPropagation();
      setIsDragging(false);
      if (e.dataTransfer.files?.length) {
        addFiles(e.dataTransfer.files);
      }
    },
    [addFiles]
  );

  const handlePaste = useCallback(
    (e: ClipboardEvent) => {
      const items = e.clipboardData?.items;
      if (!items) return;

      const files: File[] = [];
      for (const item of Array.from(items)) {
        if (item.kind === "file") {
          const file = item.getAsFile();
          if (file) files.push(file);
        }
      }
      if (files.length > 0) {
        addFiles(files);
      }
    },
    [addFiles]
  );

  const handleFileChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      if (e.target.files?.length) {
        addFiles(e.target.files);
        e.target.value = ""; // Reset for re-selection
      }
    },
    [addFiles]
  );

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const trimmedValue = inputValue.trim();
      if ((!trimmedValue && attachments.length === 0) || isSending || !onSendMessage)
        return;

      setIsSending(true);
      try {
        await onSendMessage(
          trimmedValue,
          attachments.length > 0 ? attachments : undefined
        );
        setInputValue("");
        setAttachments([]);
      } finally {
        setIsSending(false);
        inputRef.current?.focus();
      }
    },
    [inputValue, attachments, isSending, onSendMessage]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        handleSubmit(e as unknown as FormEvent);
      }
    },
    [handleSubmit]
  );

  const handleGenerateFeatures = useCallback(async () => {
    if (!onGenerateFeatures || isGenerating) return;
    setIsGenerating(true);
    setShowGenerateMenu(false);
    try {
      const features = await onGenerateFeatures();
      setGeneratedFeatures(features);
    } finally {
      setIsGenerating(false);
    }
  }, [onGenerateFeatures, isGenerating]);

  const handleGenerateVision = useCallback(async () => {
    if (!onGenerateVision || isGeneratingVision) return;
    setIsGeneratingVision(true);
    setShowGenerateMenu(false);
    try {
      const vision = await onGenerateVision();
      setGeneratedVision(vision);
    } finally {
      setIsGeneratingVision(false);
    }
  }, [onGenerateVision, isGeneratingVision]);

  const handleGenerateGoals = useCallback(async () => {
    if (!onGenerateGoals || isGeneratingGoals) return;
    setIsGeneratingGoals(true);
    setShowGenerateMenu(false);
    try {
      const goals = await onGenerateGoals();
      setGeneratedGoals(goals);
    } finally {
      setIsGeneratingGoals(false);
    }
  }, [onGenerateGoals, isGeneratingGoals]);

  const handleSaveVision = useCallback(async (
    mission: GeneratedMission | null,
    narratives: GeneratedNarrative[]
  ) => {
    if (!onSaveVision) return;
    await onSaveVision(mission, narratives);
    setGeneratedVision(null);
  }, [onSaveVision]);

  const handleSaveGoals = useCallback(async (goals: GeneratedGoal[]) => {
    if (!onSaveGoals) return;
    await onSaveGoals(goals);
    setGeneratedGoals([]);
  }, [onSaveGoals]);

  const handleGenerateSpec = useCallback(async () => {
    if (!onGenerateSpec || isGeneratingSpec) return;
    setIsGeneratingSpec(true);
    setShowGenerateMenu(false);
    try {
      await onGenerateSpec();
      setShowSpecPreview(true);
    } finally {
      setIsGeneratingSpec(false);
    }
  }, [onGenerateSpec, isGeneratingSpec]);

  const handleAcceptSpec = useCallback(async () => {
    if (!onAcceptSpec) return;
    await onAcceptSpec();
    setShowSpecPreview(false);
  }, [onAcceptSpec]);

  const handleContinueDiscussion = useCallback(() => {
    setShowSpecPreview(false);
  }, []);

  const isAnyGenerating = isGenerating || isGeneratingVision || isGeneratingGoals || isGeneratingSpec;

  return (
    <div
      className={clsx(
        "flex flex-col bg-slate-900 rounded-lg border border-slate-800",
        className
      )}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {/* Header */}
      <div className="flex flex-col gap-3 px-4 py-3 border-b border-slate-800">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h3 className="text-sm font-medium text-slate-200">Roundtable</h3>
            {sessionId && (
              <Badge variant="slate" className="text-xs mono">
                {sessionId.slice(0, 8)}
              </Badge>
            )}
            {/* New Chat button - show when there are messages */}
            {messages.length > 0 && onNewSession && (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={onNewSession}
                disabled={isLoading || !!streamingAgent}
                className="h-7 px-2 text-xs text-slate-400 hover:text-slate-200"
              >
                <Plus className="w-3.5 h-3.5 mr-1" />
                New Chat
              </Button>
            )}
          </div>

          <div className="flex items-center gap-2">
            {/* Streaming indicator */}
            {streamingAgent && (
              <div className={clsx(
                "flex items-center gap-1.5 text-xs",
                streamingAgent === "claude" ? "text-amber-400" : "text-blue-400"
              )}>
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>{streamingAgent === "claude" ? "Claude" : "Gemini"} is responding...</span>
              </div>
            )}
            {/* Loading indicator (general) */}
            {!streamingAgent && (isLoading || isGenerating) && (
              <div className="flex items-center gap-1.5 text-blue-400 text-xs">
                <Loader2 className="w-3.5 h-3.5 animate-spin" />
                <span>{isGenerating ? "Generating..." : "Thinking..."}</span>
              </div>
            )}

            {/* Connection status */}
            {!connected && (
              <div className="flex items-center gap-1.5 text-rose-400 text-xs">
                <WifiOff className="w-3.5 h-3.5" />
                <span>Disconnected</span>
              </div>
            )}
            {connected && !isLoading && !isGenerating && !streamingAgent && (
              <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
                <CircleDot className="w-3.5 h-3.5" />
                <span>Ready</span>
              </div>
            )}
          </div>
        </div>

        {/* Mode selector and tools toggle */}
        <div className="flex items-center justify-between gap-3">
          <ModeSelector
            mode={mode}
            onModeChange={onModeChange}
            disabled={isLoading || isSending || messages.length > 0}
          />

          {/* Tools/Codebase access toggles */}
          <div className="flex items-center gap-4">
            {/* Read access toggle */}
            <div className="flex items-center gap-1.5">
              <label
                htmlFor="tools-toggle"
                className={clsx(
                  "flex items-center gap-1 text-xs cursor-pointer",
                  toolsEnabled ? "text-phosphor-400" : "text-slate-500"
                )}
              >
                <FolderCode className="w-3.5 h-3.5" />
                <span>Read</span>
              </label>
              <Switch
                id="tools-toggle"
                checked={toolsEnabled}
                onCheckedChange={(enabled) => onToolsChange?.({ toolsEnabled: enabled })}
                disabled={isLoading || !!streamingAgent}
              />
            </div>

            {/* Write access toggle */}
            <div className="flex items-center gap-1.5">
              <label
                htmlFor="write-toggle"
                className={clsx(
                  "flex items-center gap-1 text-xs cursor-pointer",
                  writeEnabled ? "text-amber-400" : "text-slate-500"
                )}
              >
                <span>Write</span>
              </label>
              <Switch
                id="write-toggle"
                checked={writeEnabled}
                onCheckedChange={(enabled) => onToolsChange?.({ writeEnabled: enabled })}
                disabled={isLoading || !!streamingAgent || !toolsEnabled}
              />
            </div>

            {/* YOLO mode toggle */}
            <div className="flex items-center gap-1.5">
              <label
                htmlFor="yolo-toggle"
                className={clsx(
                  "flex items-center gap-1 text-xs cursor-pointer",
                  yoloMode ? "text-rose-400" : "text-slate-500"
                )}
                title="Auto-approve all tool actions without prompts"
              >
                <span>YOLO</span>
              </label>
              <Switch
                id="yolo-toggle"
                checked={yoloMode}
                onCheckedChange={(enabled) => onToolsChange?.({ yoloMode: enabled })}
                disabled={isLoading || !!streamingAgent || !toolsEnabled}
              />
            </div>

            {/* Tool stats badge */}
            {toolStats && toolStats.total_calls > 0 && (
              <Badge variant="slate" className="text-2xs">
                {toolStats.total_calls} calls
                {toolStats.writes > 0 && ` (${toolStats.writes} writes)`}
              </Badge>
            )}

            {/* Agent config (for generation) */}
            {mode === "spec_driven" && onAgentConfigChange && (
              <div className="flex items-center gap-1.5 border-l border-slate-700 pl-3 ml-1">
                <span className="text-xs text-slate-500">Gen:</span>
                <AgentConfigPanel
                  agentOverride={agentOverride}
                  modelOverride={modelOverride}
                  onAgentChange={(agent) => {
                    // When agent changes, also reset model if switching to "default"
                    const newModel = agent === null ? null : modelOverride;
                    onAgentConfigChange({ agentOverride: agent, modelOverride: newModel });
                  }}
                  onModelChange={(model) => {
                    // Pass current agentOverride value explicitly
                    onAgentConfigChange({ agentOverride: agentOverride, modelOverride: model });
                  }}
                  disabled={isLoading || !!streamingAgent}
                  compact
                />
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Messages */}
      <ScrollArea
        ref={scrollRef}
        className={clsx(
          "flex-1 min-h-[300px] max-h-[600px] p-4 transition-colors",
          isDragging && "bg-phosphor-500/10"
        )}
      >
        {/* Drag overlay */}
        {isDragging && (
          <div className="absolute inset-4 flex items-center justify-center border-2 border-dashed border-phosphor-500 rounded-lg bg-phosphor-500/5 z-10">
            <div className="text-center">
              <Paperclip className="w-8 h-8 text-phosphor-400 mx-auto mb-2" />
              <p className="text-sm text-phosphor-300">Drop files here</p>
            </div>
          </div>
        )}

        {messages.length > 0 ? (
          <div className="flex flex-col gap-4">
            {messages.map((message, index) => (
              <MessageBubble
                key={message.id}
                message={message}
                isLast={index === messages.length - 1}
              />
            ))}
          </div>
        ) : (
          <div className="flex flex-col items-center justify-center h-full text-slate-500 gap-2">
            <div className="flex items-center gap-2">
              <Sparkles className="w-5 h-5 text-amber-500" />
              <span>+</span>
              <Bot className="w-5 h-5 text-blue-500" />
            </div>
            <p className="text-sm">Start a conversation with Claude and Gemini</p>
            <p className="text-xs text-slate-600">
              Both agents will collaborate to help you
            </p>
          </div>
        )}
      </ScrollArea>

      {/* Generated content displays */}
      {generatedFeatures.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-800">
          <GeneratedFeaturesList
            features={generatedFeatures}
            onClose={() => setGeneratedFeatures([])}
          />
        </div>
      )}

      {generatedVision && (
        <div className="px-4 py-3 border-t border-slate-800">
          <VisionPreview
            mission={generatedVision.mission}
            narratives={generatedVision.narratives}
            onSave={handleSaveVision}
            onClose={() => setGeneratedVision(null)}
          />
        </div>
      )}

      {generatedGoals.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-800">
          <GoalsPreview
            goals={generatedGoals}
            onSave={handleSaveGoals}
            onClose={() => setGeneratedGoals([])}
          />
        </div>
      )}

      {/* Spec Preview - shown when spec exists and user hasn't dismissed it */}
      {generatedSpec && showSpecPreview && (
        <div className="px-4 py-3 border-t border-slate-800">
          <SpecPreview
            spec={generatedSpec}
            onAccept={handleAcceptSpec}
            onContinue={handleContinueDiscussion}
          />
        </div>
      )}

      {/* Generate menu (Spec-Driven mode only) */}
      {mode === "spec_driven" &&
        messages.length >= 2 &&
        !generatedFeatures.length &&
        !generatedVision &&
        !generatedGoals.length &&
        !(generatedSpec && showSpecPreview) && (
          <div className="px-4 py-3 border-t border-slate-800">
            <div className="relative">
              <Button
                type="button"
                onClick={() => setShowGenerateMenu(!showGenerateMenu)}
                disabled={isAnyGenerating || isLoading || !connected}
                className="w-full bg-phosphor-500 hover:bg-phosphor-600 text-white"
              >
                {isAnyGenerating ? (
                  <>
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                    {isGenerating ? "Extracting Features..." :
                     isGeneratingVision ? "Extracting Vision..." :
                     isGeneratingGoals ? "Extracting Goals..." :
                     "Extracting Spec..."}
                  </>
                ) : (
                  <>
                    <Wand2 className="w-4 h-4 mr-2" />
                    Generate from Discussion
                    <ChevronDown className="w-4 h-4 ml-2" />
                  </>
                )}
              </Button>
              {showGenerateMenu && !isAnyGenerating && (
                <div className="absolute bottom-full left-0 right-0 mb-1 bg-slate-800 border border-slate-700 rounded-lg shadow-lg overflow-hidden z-10">
                  <button
                    type="button"
                    onClick={handleGenerateFeatures}
                    disabled={!onGenerateFeatures}
                    className="w-full px-4 py-2.5 text-left text-sm text-slate-200 hover:bg-slate-700 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    <ListChecks className="w-4 h-4 text-phosphor-400" />
                    <div>
                      <div className="font-medium">Generate Features</div>
                      <div className="text-xs text-slate-400">Extract features with acceptance criteria</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={handleGenerateVision}
                    disabled={!onGenerateVision}
                    className="w-full px-4 py-2.5 text-left text-sm text-slate-200 hover:bg-slate-700 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed border-t border-slate-700"
                  >
                    <Eye className="w-4 h-4 text-purple-400" />
                    <div>
                      <div className="font-medium">Generate Vision</div>
                      <div className="text-xs text-slate-400">Extract mission and narratives</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={handleGenerateGoals}
                    disabled={!onGenerateGoals}
                    className="w-full px-4 py-2.5 text-left text-sm text-slate-200 hover:bg-slate-700 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed border-t border-slate-700"
                  >
                    <Target className="w-4 h-4 text-green-400" />
                    <div>
                      <div className="font-medium">Generate Goals</div>
                      <div className="text-xs text-slate-400">Extract strategic goals</div>
                    </div>
                  </button>
                  <button
                    type="button"
                    onClick={handleGenerateSpec}
                    disabled={!onGenerateSpec}
                    className="w-full px-4 py-2.5 text-left text-sm text-slate-200 hover:bg-slate-700 flex items-center gap-3 disabled:opacity-50 disabled:cursor-not-allowed border-t border-slate-700"
                  >
                    <Layers className="w-4 h-4 text-phosphor-400" />
                    <div>
                      <div className="font-medium">Generate Spec (TDD)</div>
                      <div className="text-xs text-slate-400">Extract components, capabilities, and tests</div>
                    </div>
                  </button>
                </div>
              )}
            </div>
            <p className="text-xs text-slate-500 text-center mt-2">
              AI will analyze the conversation and extract structured content
            </p>
          </div>
        )}

      {/* Error display */}
      {error && (
        <div className="px-4 py-2 border-t border-slate-800 bg-rose-950/30">
          <p className="text-xs text-rose-400">{error}</p>
        </div>
      )}

      {/* Attachments preview */}
      {attachments.length > 0 && (
        <div className="flex gap-3 px-4 py-3 border-t border-slate-800 overflow-x-auto">
          {attachments.map((att) => (
            <FilePreview
              key={att.id}
              attachment={att}
              onRemove={() => removeAttachment(att.id)}
            />
          ))}
        </div>
      )}

      {/* Input area */}
      <form
        onSubmit={handleSubmit}
        className="flex items-end gap-2 p-4 border-t border-slate-800"
      >
        {/* Hidden file input */}
        <input
          ref={fileInputRef}
          type="file"
          multiple
          className="hidden"
          onChange={handleFileChange}
          accept="image/*,.pdf,.txt,.md,.json,.csv"
        />

        {/* Upload button */}
        <Button
          type="button"
          variant="ghost"
          onClick={() => fileInputRef.current?.click()}
          disabled={isSending || !connected}
          className="h-11 w-11 p-0 text-slate-400 hover:text-slate-200 hover:bg-slate-800"
        >
          <Paperclip className="w-5 h-5" />
        </Button>

        <Textarea
          ref={inputRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder="Type a message... (paste images, drag files)"
          className="flex-1 min-h-[44px] max-h-[120px] resize-none bg-slate-800 border-slate-700 text-slate-200 placeholder:text-slate-500"
          disabled={isSending || !connected}
          rows={1}
        />
        <Button
          type="submit"
          disabled={
            (!inputValue.trim() && attachments.length === 0) ||
            isSending ||
            !connected
          }
          className="h-11 w-11 p-0 bg-phosphor-500 hover:bg-phosphor-600 disabled:opacity-50"
        >
          {isSending ? (
            <Loader2 className="w-5 h-5 animate-spin" />
          ) : (
            <Send className="w-5 h-5" />
          )}
        </Button>
      </form>
    </div>
  );
}
