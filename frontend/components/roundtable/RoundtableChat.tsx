"use client";

import { useEffect, useRef, useState, useCallback, FormEvent } from "react";
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
} from "lucide-react";

export type AgentType = "claude" | "gemini" | "user";

export interface ChatMessage {
  id: string;
  agent: AgentType;
  content: string;
  timestamp: Date;
  isStreaming?: boolean;
  tokensUsed?: number;
}

interface RoundtableChatProps {
  projectId: string;
  sessionId?: string;
  className?: string;
  onSendMessage?: (message: string, targetAgent?: AgentType) => Promise<void>;
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
      </div>
    </div>
  );
}

export function RoundtableChat({
  projectId,
  sessionId,
  className,
  onSendMessage,
  messages = [],
  isLoading = false,
  connected = true,
  error = null,
}: RoundtableChatProps) {
  const [inputValue, setInputValue] = useState("");
  const [isSending, setIsSending] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new messages
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
    }
  }, [messages]);

  const handleSubmit = useCallback(
    async (e: FormEvent) => {
      e.preventDefault();
      const trimmedValue = inputValue.trim();
      if (!trimmedValue || isSending || !onSendMessage) return;

      setIsSending(true);
      try {
        await onSendMessage(trimmedValue);
        setInputValue("");
      } finally {
        setIsSending(false);
        inputRef.current?.focus();
      }
    },
    [inputValue, isSending, onSendMessage]
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

  return (
    <div
      className={clsx(
        "flex flex-col bg-slate-900 rounded-lg border border-slate-800",
        className
      )}
    >
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-slate-800">
        <div className="flex items-center gap-3">
          <h3 className="text-sm font-medium text-slate-200">Roundtable</h3>
          {sessionId && (
            <Badge variant="slate" className="text-xs mono">
              {sessionId}
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-2">
          {/* Loading indicator */}
          {isLoading && (
            <div className="flex items-center gap-1.5 text-blue-400 text-xs">
              <Loader2 className="w-3.5 h-3.5 animate-spin" />
              <span>Thinking...</span>
            </div>
          )}

          {/* Connection status */}
          {!connected && (
            <div className="flex items-center gap-1.5 text-rose-400 text-xs">
              <WifiOff className="w-3.5 h-3.5" />
              <span>Disconnected</span>
            </div>
          )}
          {connected && !isLoading && (
            <div className="flex items-center gap-1.5 text-emerald-400 text-xs">
              <CircleDot className="w-3.5 h-3.5" />
              <span>Ready</span>
            </div>
          )}
        </div>
      </div>

      {/* Messages */}
      <ScrollArea
        ref={scrollRef}
        className="flex-1 min-h-[300px] max-h-[600px] p-4"
      >
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

      {/* Error display */}
      {error && (
        <div className="px-4 py-2 border-t border-slate-800 bg-rose-950/30">
          <p className="text-xs text-rose-400">{error}</p>
        </div>
      )}

      {/* Input area */}
      <form
        onSubmit={handleSubmit}
        className="flex items-end gap-2 p-4 border-t border-slate-800"
      >
        <Textarea
          ref={inputRef}
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder="Type a message... (Enter to send, Shift+Enter for new line)"
          className="flex-1 min-h-[44px] max-h-[120px] resize-none bg-slate-800 border-slate-700 text-slate-200 placeholder:text-slate-500"
          disabled={isSending || !connected}
          rows={1}
        />
        <Button
          type="submit"
          disabled={!inputValue.trim() || isSending || !connected}
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
