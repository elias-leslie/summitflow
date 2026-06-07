import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { formatNotePaste } from './pasteFormat';
import type { EditMode } from './useNoteEditorState';

interface NoteEditorContentProps {
    mode: EditMode;
    content: string;
    onContentChange: (v: string) => void;
}

export function NoteEditorContent({ mode, content, onContentChange }: NoteEditorContentProps) {
    if (mode === 'edit') {
        const handlePaste = (event: React.ClipboardEvent<HTMLTextAreaElement>) => {
            const pastedText = event.clipboardData.getData('text/plain');
            const pastedHtml = event.clipboardData.getData('text/html');
            const formattedPaste = formatNotePaste(pastedText, pastedHtml);
            if (!formattedPaste || formattedPaste === pastedText) return;

            event.preventDefault();
            const textarea = event.currentTarget;
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            const nextContent = `${content.slice(0, start)}${formattedPaste}${content.slice(end)}`;
            onContentChange(nextContent);

            requestAnimationFrame(() => {
                textarea.selectionStart = start + formattedPaste.length;
                textarea.selectionEnd = start + formattedPaste.length;
            });
        };

        return (
            <div className="flex-1 min-h-0 overflow-y-auto">
                <textarea
                    value={content}
                    onChange={e => onContentChange(e.target.value)}
                    onPaste={handlePaste}
                    placeholder="Write something..."
                    className="w-full h-full px-4 py-3 bg-transparent text-sm text-slate-300 placeholder:text-slate-700 outline-none resize-none font-mono leading-relaxed"
                    spellCheck={false}
                />
            </div>
        );
    }
    return (
        <div className="flex-1 min-h-0 overflow-auto">
            <div className="px-4 py-3 text-sm text-slate-300 prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-a:text-[var(--color-phosphor-400,#33f7ff)] prose-code:text-amber-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-700/50 prose-table:w-full prose-table:border-collapse prose-table:text-xs prose-th:border prose-th:border-slate-700/70 prose-th:bg-slate-800/80 prose-th:px-3 prose-th:py-2 prose-th:text-left prose-th:align-top prose-td:border prose-td:border-slate-800 prose-td:px-3 prose-td:py-2 prose-td:align-top prose-td:break-words">
                {content
                    ? <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown>
                    : <p className="text-slate-600 italic">Nothing here yet.</p>
                }
            </div>
        </div>
    );
}
