"use client";

import { memo, useRef, useCallback, FormEvent } from "react";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Send, Loader2, Paperclip, X, FileText, Image as ImageIcon, File } from "lucide-react";
import type { FileAttachment } from "../../hooks/useFileAttachments";

interface RoundtableInputFormProps {
  inputValue: string;
  onInputChange: (value: string) => void;
  onSubmit: (e: FormEvent) => void;
  onKeyDown: (e: React.KeyboardEvent<HTMLTextAreaElement>) => void;
  onPaste: (e: React.ClipboardEvent) => void;
  onFileChange: (e: React.ChangeEvent<HTMLInputElement>) => void;
  attachments: FileAttachment[];
  onRemoveAttachment: (id: string) => void;
  isSending: boolean;
  connected: boolean;
}

const FilePreview = memo(function FilePreview({
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
});

export const RoundtableInputForm = memo(function RoundtableInputForm({
  inputValue,
  onInputChange,
  onSubmit,
  onKeyDown,
  onPaste,
  onFileChange,
  attachments,
  onRemoveAttachment,
  isSending,
  connected,
}: RoundtableInputFormProps) {
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleSubmit = useCallback(
    (e: FormEvent) => {
      onSubmit(e);
      inputRef.current?.focus();
    },
    [onSubmit]
  );

  return (
    <>
      {/* Attachments preview */}
      {attachments.length > 0 && (
        <div className="flex gap-3 px-4 py-3 border-t border-slate-800 overflow-x-auto">
          {attachments.map((att) => (
            <FilePreview
              key={att.id}
              attachment={att}
              onRemove={() => onRemoveAttachment(att.id)}
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
          onChange={onFileChange}
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
          onChange={(e) => onInputChange(e.target.value)}
          onKeyDown={onKeyDown}
          onPaste={onPaste}
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
    </>
  );
});
