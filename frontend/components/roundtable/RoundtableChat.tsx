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
} from "lucide-react";

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
  feature_id: string;
  name: string;
  category: string;
  priority: number;
  acceptance_criteria: { id: string; description: string }[];
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
  messages?: ChatMessage[];
  isLoading?: boolean;
  connected?: boolean;
  error?: string | null;
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
          <span className="text-[10px] text-slate-400 truncate max-w-[56px] px-1">
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
      <span className="absolute -bottom-5 left-0 right-0 text-[9px] text-slate-500 truncate text-center">
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
            key={feat.feature_id}
            className="flex items-start gap-3 p-3 bg-slate-800/50 rounded-lg"
          >
            <ListChecks className="w-4 h-4 text-phosphor-400 mt-0.5 flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2">
                <span className="text-xs text-slate-500 mono">{feat.feature_id}</span>
                <Badge variant="phosphor" className="text-[10px]">
                  P{feat.priority}
                </Badge>
                <Badge variant="slate" className="text-[10px]">
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
  messages = [],
  isLoading = false,
  connected = true,
  error = null,
}: RoundtableChatProps) {
  const [inputValue, setInputValue] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [isGenerating, setIsGenerating] = useState(false);
  const [attachments, setAttachments] = useState<FileAttachment[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [generatedFeatures, setGeneratedFeatures] = useState<GeneratedFeature[]>([]);
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
    try {
      const features = await onGenerateFeatures();
      setGeneratedFeatures(features);
    } finally {
      setIsGenerating(false);
    }
  }, [onGenerateFeatures, isGenerating]);

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
          </div>

          <div className="flex items-center gap-2">
            {/* Loading indicator */}
            {(isLoading || isGenerating) && (
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
            {connected && !isLoading && !isGenerating && (
              <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
                <CircleDot className="w-3.5 h-3.5" />
                <span>Ready</span>
              </div>
            )}
          </div>
        </div>

        {/* Mode selector */}
        <ModeSelector
          mode={mode}
          onModeChange={onModeChange}
          disabled={isLoading || isSending || messages.length > 0}
        />
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

      {/* Generated features display */}
      {generatedFeatures.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-800">
          <GeneratedFeaturesList
            features={generatedFeatures}
            onClose={() => setGeneratedFeatures([])}
          />
        </div>
      )}

      {/* Generate Features button (Spec-Driven mode only) */}
      {mode === "spec_driven" &&
        messages.length >= 2 &&
        generatedFeatures.length === 0 && (
          <div className="px-4 py-3 border-t border-slate-800">
            <Button
              type="button"
              onClick={handleGenerateFeatures}
              disabled={isGenerating || isLoading || !connected}
              className="w-full bg-phosphor-500 hover:bg-phosphor-600 text-white"
            >
              {isGenerating ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  Extracting Features...
                </>
              ) : (
                <>
                  <Wand2 className="w-4 h-4 mr-2" />
                  Generate Features from Discussion
                </>
              )}
            </Button>
            <p className="text-xs text-slate-500 text-center mt-2">
              AI will analyze the conversation and create features with acceptance criteria
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
