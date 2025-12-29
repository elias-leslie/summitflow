"use client";

import { useEffect, useRef, useState, useCallback, FormEvent, memo } from "react";
import { useFileAttachments, FileAttachment } from "../../hooks/useFileAttachments";
import { clsx } from "clsx";
import { ScrollArea } from "../ui/scroll-area";
import { Badge } from "../ui/badge";
import { Sparkles, Bot, Paperclip, X, CheckCircle, ListChecks, FileText } from "lucide-react";
import { AGENT_STYLES } from "@/lib/constants/agentStyles";
import { VisionPreview, GeneratedMission, GeneratedNarrative } from "./VisionPreview";
import { GoalsPreview, GeneratedGoal } from "./GoalsPreview";
import { SpecPreview, GeneratedSpec, SpecComponent, SpecCapability, SpecTest } from "./SpecPreview";
import { RoundtableHeader } from "./RoundtableHeader";
import { RoundtableInputForm } from "./RoundtableInputForm";
import { GenerateMenu, useGenerateMenuItems } from "./GenerateMenu";
import type { AgentConfig } from "../settings/AgentConfigPanel";

// Re-export spec types for consumers
export type { GeneratedSpec, SpecComponent, SpecCapability, SpecTest };

export type AgentType = "claude" | "gemini" | "user";
export type RoundtableMode = "spec_driven" | "quick";

// Re-export FileAttachment for consumers
export type { FileAttachment };

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
  onSendMessage?: (message: string, attachments?: FileAttachment[], targetAgent?: AgentType) => Promise<void>;
  onGenerateFeatures?: () => Promise<GeneratedFeature[]>;
  onGenerateVision?: () => Promise<GeneratedVision>;
  onGenerateGoals?: () => Promise<GeneratedGoal[]>;
  onGenerateSpec?: () => Promise<GeneratedSpec>;
  onSaveVision?: (mission: GeneratedMission | null, narratives: GeneratedNarrative[]) => Promise<void>;
  onSaveGoals?: (goals: GeneratedGoal[]) => Promise<void>;
  onAcceptSpec?: () => Promise<void>;
  onNewSession?: () => void;
  generatedSpec?: GeneratedSpec | null;
  messages?: ChatMessage[];
  isLoading?: boolean;
  streamingAgent?: "claude" | "gemini" | null;
  connected?: boolean;
  error?: string | null;
  toolsEnabled?: boolean;
  writeEnabled?: boolean;
  yoloMode?: boolean;
  toolStats?: ToolStats;
  onToolsChange?: (settings: Partial<ToolsSettings>) => void;
  agentOverride?: string | null;
  modelOverride?: string | null;
  onAgentConfigChange?: (config: AgentConfig) => void;
}

// Message attachment display
const MessageAttachments = memo(function MessageAttachments({ attachments }: { attachments: FileAttachment[] }) {
  return (
    <div className="flex flex-wrap gap-2 mt-2">
      {attachments.map((attachment) => (
        <div key={attachment.id} className="flex-shrink-0">
          {attachment.type === "image" && attachment.previewUrl ? (
            <div className="w-24 h-24 rounded-lg overflow-hidden border border-slate-600">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={attachment.previewUrl} alt={attachment.file.name} className="w-full h-full object-cover" />
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
});

// Individual message bubble
const MessageBubble = memo(function MessageBubble({ message, isLast }: { message: ChatMessage; isLast: boolean }) {
  const config = AGENT_STYLES[message.agent];
  const Icon = config.icon;
  const isUser = message.agent === "user";

  return (
    <div className={clsx("flex gap-3 p-4 rounded-lg border", config.bgColor, config.borderColor, isUser && "flex-row-reverse")}>
      <div className={clsx("flex-shrink-0 w-8 h-8 rounded-full flex items-center justify-center", config.iconBg)}>
        <Icon className={clsx("w-4 h-4", config.textColor)} />
      </div>
      <div className={clsx("flex-1 min-w-0", isUser && "text-right")}>
        <div className={clsx("flex items-center gap-2 mb-1", isUser && "justify-end")}>
          <span className={clsx("text-sm font-medium", config.textColor)}>{config.name}</span>
          <span className="text-xs text-slate-500">
            {message.timestamp.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
          {message.tokensUsed && message.tokensUsed > 0 && (
            <span className="text-xs text-slate-500 mono">{message.tokensUsed.toLocaleString()} tokens</span>
          )}
        </div>
        <div className={clsx("text-sm whitespace-pre-wrap break-words", config.textColor)}>
          {message.content}
          {message.isStreaming && isLast && <span className="inline-block w-2 h-4 bg-current animate-pulse ml-0.5" />}
        </div>
        {message.attachments && message.attachments.length > 0 && <MessageAttachments attachments={message.attachments} />}
      </div>
    </div>
  );
});

// Generated features display
function GeneratedFeaturesList({ features, onClose }: { features: GeneratedFeature[]; onClose: () => void }) {
  return (
    <div className="p-4 bg-phosphor-950/50 border border-phosphor-900 rounded-lg">
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <CheckCircle className="w-5 h-5 text-phosphor-400" />
          <h4 className="text-sm font-medium text-phosphor-200">
            {features.length} Feature{features.length !== 1 ? "s" : ""} Generated
          </h4>
        </div>
        <button onClick={onClose} className="text-slate-400 hover:text-slate-200">
          <X className="w-4 h-4" />
        </button>
      </div>
      <div className="space-y-2">
        {features.map((feat) => (
          <div key={feat.capability_id} className="flex items-start gap-3 p-3 bg-slate-800/50 rounded-lg">
            <ListChecks className="w-4 h-4 text-phosphor-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 mono">{feat.capability_id}</span>
                <Badge variant="phosphor" className="text-2xs">P{feat.priority}</Badge>
                <Badge variant="slate" className="text-2xs">{feat.category}</Badge>
              </div>
              <p className="text-sm text-slate-200 mt-1">{feat.name}</p>
              <p className="text-xs text-slate-500 mt-0.5">{feat.acceptance_criteria.length} criteria</p>
            </div>
          </div>
        ))}
      </div>
      <p className="text-xs text-slate-500 mt-3">Features added to your Kanban board in backlog.</p>
    </div>
  );
}

export function RoundtableChat({
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
  const [generatedFeatures, setGeneratedFeatures] = useState<GeneratedFeature[]>([]);
  const [generatedVision, setGeneratedVision] = useState<GeneratedVision | null>(null);
  const [generatedGoals, setGeneratedGoals] = useState<GeneratedGoal[]>([]);
  const [showGenerateMenu, setShowGenerateMenu] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);

  const { attachments, isDragging, removeAttachment, clearAttachments, handleDragOver, handleDragLeave, handleDrop, handlePaste, handleFileChange } = useFileAttachments();

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = useCallback(async (e: FormEvent) => {
    e.preventDefault();
    const trimmedValue = inputValue.trim();
    if ((!trimmedValue && attachments.length === 0) || isSending || !onSendMessage) return;

    setIsSending(true);
    try {
      await onSendMessage(trimmedValue, attachments.length > 0 ? attachments : undefined);
      setInputValue("");
      clearAttachments();
    } finally {
      setIsSending(false);
    }
  }, [inputValue, attachments, isSending, onSendMessage, clearAttachments]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e as unknown as FormEvent);
    }
  }, [handleSubmit]);

  // Generate handlers
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

  const handleSaveVision = useCallback(async (mission: GeneratedMission | null, narratives: GeneratedNarrative[]) => {
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

  const isAnyGenerating = isGenerating || isGeneratingVision || isGeneratingGoals || isGeneratingSpec;

  const generateMenuItems = useGenerateMenuItems({
    onGenerateFeatures: handleGenerateFeatures,
    onGenerateVision: handleGenerateVision,
    onGenerateGoals: handleGenerateGoals,
    onGenerateSpec: handleGenerateSpec,
    isGenerating,
    isGeneratingVision,
    isGeneratingGoals,
    isGeneratingSpec,
  });

  const showGenerateSection = mode === "spec_driven" && messages.length >= 2 &&
    !generatedFeatures.length && !generatedVision && !generatedGoals.length && !(generatedSpec && showSpecPreview);

  return (
    <div
      className={clsx("flex flex-col bg-slate-900 rounded-lg border border-slate-800", className)}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <RoundtableHeader
        sessionId={sessionId}
        mode={mode}
        onModeChange={onModeChange}
        connected={connected}
        isLoading={isLoading}
        isGenerating={isGenerating}
        streamingAgent={streamingAgent}
        hasMessages={messages.length > 0}
        onNewSession={onNewSession}
        toolsEnabled={toolsEnabled}
        writeEnabled={writeEnabled}
        yoloMode={yoloMode}
        toolStats={toolStats}
        onToolsChange={onToolsChange}
        agentOverride={agentOverride}
        modelOverride={modelOverride}
        onAgentConfigChange={onAgentConfigChange}
      />

      {/* Messages */}
      <ScrollArea
        ref={scrollRef}
        className={clsx("flex-1 min-h-[300px] max-h-[600px] p-4 transition-colors", isDragging && "bg-phosphor-500/10")}
      >
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
              <MessageBubble key={message.id} message={message} isLast={index === messages.length - 1} />
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
            <p className="text-xs text-slate-600">Both agents will collaborate to help you</p>
          </div>
        )}
      </ScrollArea>

      {/* Generated content displays */}
      {generatedFeatures.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-800">
          <GeneratedFeaturesList features={generatedFeatures} onClose={() => setGeneratedFeatures([])} />
        </div>
      )}

      {generatedVision && (
        <div className="px-4 py-3 border-t border-slate-800">
          <VisionPreview mission={generatedVision.mission} narratives={generatedVision.narratives} onSave={handleSaveVision} onClose={() => setGeneratedVision(null)} />
        </div>
      )}

      {generatedGoals.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-800">
          <GoalsPreview goals={generatedGoals} onSave={handleSaveGoals} onClose={() => setGeneratedGoals([])} />
        </div>
      )}

      {generatedSpec && showSpecPreview && (
        <div className="px-4 py-3 border-t border-slate-800">
          <SpecPreview spec={generatedSpec} onAccept={handleAcceptSpec} onContinue={() => setShowSpecPreview(false)} />
        </div>
      )}

      {/* Generate menu */}
      {showGenerateSection && (
        <div className="px-4 py-3 border-t border-slate-800">
          <GenerateMenu
            items={generateMenuItems}
            isOpen={showGenerateMenu}
            onToggle={() => setShowGenerateMenu(!showGenerateMenu)}
            disabled={isLoading || !connected}
            isAnyLoading={isAnyGenerating}
          />
          <p className="text-xs text-slate-500 text-center mt-2">AI will analyze the conversation and extract structured content</p>
        </div>
      )}

      {/* Error display */}
      {error && (
        <div className="px-4 py-2 border-t border-slate-800 bg-rose-950/30">
          <p className="text-xs text-rose-400">{error}</p>
        </div>
      )}

      <RoundtableInputForm
        inputValue={inputValue}
        onInputChange={setInputValue}
        onSubmit={handleSubmit}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        onFileChange={handleFileChange}
        attachments={attachments}
        onRemoveAttachment={removeAttachment}
        isSending={isSending}
        connected={connected}
      />
    </div>
  );
}
