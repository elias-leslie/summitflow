import { useState, useEffect, useRef, useCallback } from 'react';
import { Pin, PinOff, Eye, Pencil, X, Trash2, Wand2, Loader2, Check, XCircle, History, RotateCcw } from 'lucide-react';
import clsx from 'clsx';
import Markdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useUpdateNote, useDeleteNote } from './useNotes';
import { useNotesContext } from './NotesProvider';
import { PromptActions } from './PromptActions';
import type { Note, FormatProposal, NoteVersion } from './types';

interface NoteEditorProps {
    note: Note;
    onDeleted: () => void;
}

export function NoteEditor({ note, onDeleted }: NoteEditorProps) {
    const [title, setTitle] = useState(note.title);
    const [content, setContent] = useState(note.content);
    const [tags, setTags] = useState<string[]>(note.tags);
    const [tagInput, setTagInput] = useState('');
    const [mode, setMode] = useState<'edit' | 'preview'>('edit');
    const [saveState, setSaveState] = useState<'idle' | 'saving' | 'saved'>('idle');
    const [confirmDelete, setConfirmDelete] = useState(false);

    // Format state
    const [formatState, setFormatState] = useState<'idle' | 'pending' | 'ready' | 'failed'>('idle');
    const [proposal, setProposal] = useState<FormatProposal | null>(null);
    const autoFormatAttemptedRef = useRef(false);
    const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

    // Version history
    const [showHistory, setShowHistory] = useState(false);
    const [versions, setVersions] = useState<NoteVersion[]>([]);
    const [loadingVersions, setLoadingVersions] = useState(false);

    const { api } = useNotesContext();
    const updateNote = useUpdateNote();
    const deleteNote = useDeleteNote();
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pendingRef = useRef<{ noteId: string; data: Record<string, unknown> } | null>(null);
    const mutateRef = useRef(updateNote.mutate);
    mutateRef.current = updateNote.mutate;

    // Reset state on note switch
    const prevIdRef = useRef(note.id);
    useEffect(() => {
        if (prevIdRef.current === note.id) return;
        if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
        if (pendingRef.current) { mutateRef.current(pendingRef.current); pendingRef.current = null; }
        prevIdRef.current = note.id;
        setTitle(note.title);
        setContent(note.content);
        setTags(note.tags);
        setTagInput('');
        setSaveState('idle');
        setConfirmDelete(false);
        setFormatState('idle');
        setProposal(null);
        setShowHistory(false);
        setVersions([]);
        autoFormatAttemptedRef.current = false;
        if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [note.id]);

    // Check for existing pending/complete proposal on mount
    useEffect(() => {
        api.getFormatProposal(note.id).then(p => {
            if (!p) return;
            if (p.status === 'complete') {
                setProposal(p);
                setFormatState('ready');
            } else if (p.status === 'pending') {
                setProposal(p);
                setFormatState('pending');
                startPolling(p.note_id);
            }
        }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [note.id]);

    // Flush on unmount
    useEffect(() => {
        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
            if (pendingRef.current) mutateRef.current(pendingRef.current);
            if (pollRef.current) clearInterval(pollRef.current);
        };
    }, []);

    // Poll for proposal completion
    const startPolling = useCallback((noteId: string) => {
        if (pollRef.current) clearInterval(pollRef.current);
        pollRef.current = setInterval(async () => {
            try {
                const p = await api.getFormatProposal(noteId);
                if (!p || p.status === 'discarded' || p.status === 'accepted') {
                    setFormatState('idle');
                    setProposal(null);
                    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                } else if (p.status === 'complete') {
                    setProposal(p);
                    setFormatState('ready');
                    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                } else if (p.status === 'failed') {
                    setFormatState('failed');
                    setProposal(null);
                    if (pollRef.current) { clearInterval(pollRef.current); pollRef.current = null; }
                }
            } catch {
                // keep polling
            }
        }, 2000);
    }, [api]);

    const save = useCallback((updates: { title?: string; content?: string; tags?: string[]; pinned?: boolean }) => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        const payload = { noteId: note.id, data: updates };
        pendingRef.current = payload;
        debounceRef.current = setTimeout(() => {
            pendingRef.current = null;
            setSaveState('saving');
            mutateRef.current(payload, {
                onSuccess: () => { setSaveState('saved'); setTimeout(() => setSaveState('idle'), 1500); },
                onError: () => setSaveState('idle'),
            });
        }, 500);
    }, [note.id]);

    // Start background format
    const startFormat = useCallback(async () => {
        if (content.trim().length < 50) return;
        setFormatState('pending');
        try {
            const p = await api.startFormat(note.id, content, title);
            setProposal(p);
            startPolling(note.id);
        } catch (err) {
            console.warn('Format request failed:', err);
            setFormatState('failed');
        }
    }, [api, note.id, content, title, startPolling]);

    // Accept proposal — server-side applies changes + creates version
    const acceptProposal = useCallback(async () => {
        if (!proposal || (!proposal.proposed_title && !proposal.proposed_content)) return;
        try {
            await api.resolveProposal(proposal.id, 'accept');
            if (proposal.proposed_title) setTitle(proposal.proposed_title);
            if (proposal.proposed_content) setContent(proposal.proposed_content);
            autoFormatAttemptedRef.current = true;
            setProposal(null);
            setFormatState('idle');
            setSaveState('saved');
            setTimeout(() => setSaveState('idle'), 1500);
        } catch (err) {
            console.warn('Accept proposal failed:', err);
        }
    }, [proposal, api, title, content]);

    const discardProposal = useCallback(async () => {
        if (!proposal) return;
        try { await api.resolveProposal(proposal.id, 'discard'); } catch {}
        setProposal(null);
        setFormatState('idle');
        autoFormatAttemptedRef.current = true;
    }, [proposal, api]);

    // Auto-title on load
    useEffect(() => {
        const isUntitled = !note.title.trim() || note.title === 'Untitled';
        if (isUntitled && note.content.trim().length >= 50 && !autoFormatAttemptedRef.current) {
            autoFormatAttemptedRef.current = true;
            api.generateTitle(note.content).then(result => {
                if (result.title) {
                    setTitle(result.title);
                    mutateRef.current({ noteId: note.id, data: { title: result.title } });
                }
            }).catch(() => {});
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [note.id]);

    // Load version history
    const loadVersions = useCallback(async () => {
        setLoadingVersions(true);
        try {
            const v = await api.listVersions(note.id);
            setVersions(v);
        } catch {}
        setLoadingVersions(false);
    }, [api, note.id]);

    const toggleHistory = useCallback(() => {
        if (!showHistory) loadVersions();
        setShowHistory(v => !v);
    }, [showHistory, loadVersions]);

    const revertToVersion = useCallback(async (versionId: string) => {
        try {
            const reverted = await api.revertToVersion(note.id, versionId);
            setTitle(reverted.title);
            setContent(reverted.content);
            setTags(reverted.tags);
            setShowHistory(false);
            setSaveState('saved');
            setTimeout(() => setSaveState('idle'), 1500);
        } catch (err) {
            console.warn('Revert failed:', err);
        }
    }, [api, note.id]);

    const handleTitleChange = (val: string) => {
        setTitle(val);
        save({ title: val });
        if (val.trim()) autoFormatAttemptedRef.current = true;
    };

    const handleContentChange = (val: string) => {
        setContent(val);
        save({ content: val });
    };

    const handleTagKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if ((e.key === 'Enter' || e.key === ',') && tagInput.trim()) {
            e.preventDefault();
            const tag = tagInput.trim().replace(/,/g, '');
            if (tag && !tags.includes(tag)) { const next = [...tags, tag]; setTags(next); save({ tags: next }); }
            setTagInput('');
        }
        if (e.key === 'Backspace' && !tagInput && tags.length > 0) {
            const next = tags.slice(0, -1); setTags(next); save({ tags: next });
        }
    };

    const removeTag = (tag: string) => { const next = tags.filter(t => t !== tag); setTags(next); save({ tags: next }); };
    const togglePin = () => { save({ pinned: !note.pinned }); };
    const handleDelete = () => {
        if (!confirmDelete) { setConfirmDelete(true); setTimeout(() => setConfirmDelete(false), 3000); return; }
        deleteNote.mutate(note.id, { onSuccess: onDeleted });
    };

    function relativeTime(dateStr: string | null): string {
        if (!dateStr) return '';
        const diff = Date.now() - new Date(dateStr).getTime();
        const mins = Math.floor(diff / 60_000);
        if (mins < 1) return 'just now';
        if (mins < 60) return `${mins}m ago`;
        const hrs = Math.floor(mins / 60);
        if (hrs < 24) return `${hrs}h ago`;
        return `${Math.floor(hrs / 24)}d ago`;
    }

    // ── Diff preview mode ──
    if (proposal && formatState === 'ready' && (proposal.proposed_title || proposal.proposed_content)) {
        const titleChanged = !!proposal.proposed_title && proposal.proposed_title !== title;
        const contentChanged = proposal.proposed_content !== content;
        return (
            <div className="flex flex-col h-full min-w-0" style={{ backgroundColor: '#0f172a' }}>
                <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/50">
                    <div className="flex items-center gap-2">
                        <Wand2 className="w-3.5 h-3.5 text-amber-400" />
                        <span className="text-xs font-medium text-slate-300">Proposed Changes</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                        <button type="button" onClick={acceptProposal}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 hover:bg-emerald-500/25 transition-colors">
                            <Check className="w-3 h-3" /> Accept
                        </button>
                        <button type="button" onClick={discardProposal}
                            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-md text-xs font-medium bg-slate-800 text-slate-400 border border-slate-700 hover:text-slate-300 transition-colors">
                            <XCircle className="w-3 h-3" /> Discard
                        </button>
                    </div>
                </div>
                {titleChanged && (
                    <div className="px-4 py-2 border-b border-slate-800/50">
                        <span className="text-[10px] text-slate-500 uppercase tracking-wider">Title</span>
                        <div className="flex gap-3 mt-1">
                            <div className="flex-1 min-w-0">
                                <span className="text-[10px] text-rose-400/70 block mb-0.5">Current</span>
                                <span className="text-sm text-slate-400 line-through">{title || 'Untitled'}</span>
                            </div>
                            <div className="flex-1 min-w-0">
                                <span className="text-[10px] text-emerald-400/70 block mb-0.5">Proposed</span>
                                <span className="text-sm text-slate-200 font-medium">{proposal.proposed_title}</span>
                            </div>
                        </div>
                    </div>
                )}
                <div className="flex flex-1 min-h-0 overflow-hidden">
                    <div className="flex-1 min-w-0 border-r border-slate-800/50 overflow-y-auto">
                        <div className="px-3 py-1.5 border-b border-slate-800/30 sticky top-0" style={{ backgroundColor: '#0f172a' }}>
                            <span className="text-[10px] text-rose-400/70 uppercase tracking-wider">Current</span>
                        </div>
                        {contentChanged ? (
                            <div className="px-3 py-2 text-xs text-slate-400 font-mono leading-relaxed whitespace-pre-wrap">{content || '(empty)'}</div>
                        ) : (
                            <div className="px-3 py-4 text-center text-[11px] text-slate-600">Content unchanged</div>
                        )}
                    </div>
                    <div className="flex-1 min-w-0 overflow-y-auto">
                        <div className="px-3 py-1.5 border-b border-slate-800/30 sticky top-0" style={{ backgroundColor: '#0f172a' }}>
                            <span className="text-[10px] text-emerald-400/70 uppercase tracking-wider">Proposed</span>
                        </div>
                        {contentChanged ? (
                            <div className="px-3 py-2 text-sm text-slate-300 prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-code:text-amber-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-700/50">
                                <Markdown remarkPlugins={[remarkGfm]}>{proposal.proposed_content ?? ''}</Markdown>
                            </div>
                        ) : (
                            <div className="px-3 py-4 text-center text-[11px] text-slate-600">Content unchanged</div>
                        )}
                    </div>
                </div>
            </div>
        );
    }

    // ── Version history view ──
    if (showHistory) {
        return (
            <div className="flex flex-col h-full min-w-0" style={{ backgroundColor: '#0f172a' }}>
                <div className="flex items-center justify-between px-4 py-2.5 border-b border-slate-700/50">
                    <div className="flex items-center gap-2">
                        <History className="w-3.5 h-3.5 text-[var(--color-phosphor-400,#33f7ff)]" />
                        <span className="text-xs font-medium text-slate-300">Version History</span>
                        <span className="text-[10px] text-slate-500">({versions.length})</span>
                    </div>
                    <button type="button" onClick={() => setShowHistory(false)}
                        className="p-1 text-slate-500 hover:text-slate-300 rounded transition-colors">
                        <X className="w-3.5 h-3.5" />
                    </button>
                </div>
                <div className="flex-1 overflow-y-auto">
                    {loadingVersions ? (
                        <div className="px-4 py-6 text-center text-xs text-slate-600">Loading...</div>
                    ) : versions.length === 0 ? (
                        <div className="px-4 py-6 text-center text-xs text-slate-600">No versions yet</div>
                    ) : (
                        versions.map(v => (
                            <div key={v.id} className="px-4 py-3 border-b border-slate-800/50 hover:bg-slate-800/30 transition-colors group">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="text-xs text-slate-300 font-medium">v{v.version}</span>
                                        <span className="text-[10px] text-slate-600">{relativeTime(v.created_at)}</span>
                                        <span className={clsx(
                                            'text-[10px] px-1.5 py-0.5 rounded border',
                                            v.change_source === 'format_accept' ? 'text-amber-400/70 border-amber-500/20 bg-amber-500/5' :
                                            v.change_source === 'revert' ? 'text-[var(--color-phosphor-400,#33f7ff)]/70 border-[var(--color-phosphor-500,#00f5ff)]/20 bg-[var(--color-phosphor-500,#00f5ff)]/5' :
                                            'text-slate-500 border-slate-700/50 bg-slate-800/30',
                                        )}>
                                            {v.change_source.replace('_', ' ')}
                                        </span>
                                    </div>
                                    <button type="button" onClick={() => revertToVersion(v.id)}
                                        className="opacity-0 group-hover:opacity-100 inline-flex items-center gap-1 px-2 py-1 rounded text-[10px] font-medium text-[var(--color-phosphor-400,#33f7ff)] border border-[var(--color-phosphor-500,#00f5ff)]/20 hover:bg-[var(--color-phosphor-500,#00f5ff)]/10 transition-all">
                                        <RotateCcw className="w-2.5 h-2.5" /> Revert
                                    </button>
                                </div>
                                <p className="text-[11px] text-slate-400 mt-1 truncate">{v.title || 'Untitled'}</p>
                                <p className="text-[10px] text-slate-600 mt-0.5 line-clamp-2">{v.content.substring(0, 150)}</p>
                            </div>
                        ))
                    )}
                </div>
            </div>
        );
    }

    // ── Normal editor mode ──
    return (
        <div className="flex flex-col h-full min-w-0" style={{ backgroundColor: '#0f172a' }}>
            {/* Editor header */}
            <div className="flex items-center gap-3 px-4 py-2.5 border-b border-slate-700/50">
                <input
                    value={title}
                    onChange={e => handleTitleChange(e.target.value)}
                    placeholder="Untitled"
                    className="flex-1 bg-transparent text-slate-100 text-sm font-semibold placeholder:text-slate-600 outline-none min-w-0"
                />
                <div className="flex items-center gap-0.5 flex-shrink-0">
                    {formatState === 'pending' && (
                        <span className="text-[10px] text-amber-400/80 tabular-nums mr-1.5 animate-pulse">formatting...</span>
                    )}
                    {formatState === 'failed' && (
                        <span className="text-[10px] text-rose-400/70 tabular-nums mr-1.5">format failed</span>
                    )}
                    {formatState !== 'pending' && saveState !== 'idle' && (
                        <span className={clsx(
                            'text-[10px] tabular-nums mr-1.5 transition-colors',
                            saveState === 'saving' ? 'text-slate-500' : 'text-emerald-400/80',
                        )}>
                            {saveState === 'saving' ? 'saving...' : 'saved'}
                        </span>
                    )}
                    <button type="button" onClick={startFormat}
                        disabled={formatState === 'pending' || content.trim().length < 50}
                        className={clsx(
                            'p-1.5 rounded-md transition-all duration-150',
                            formatState === 'pending' ? 'text-amber-400' :
                            'text-slate-500 hover:text-amber-400 hover:bg-slate-800 disabled:opacity-30 disabled:cursor-not-allowed',
                        )}
                        title="Format note (title + content cleanup)">
                        {formatState === 'pending' ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wand2 className="w-3.5 h-3.5" />}
                    </button>
                    <button type="button" onClick={toggleHistory}
                        className="p-1.5 rounded-md transition-all duration-150 text-slate-500 hover:text-[var(--color-phosphor-400,#33f7ff)] hover:bg-slate-800"
                        title="Version history">
                        <History className="w-3.5 h-3.5" />
                    </button>
                    <button type="button" onClick={togglePin}
                        className={clsx(
                            'p-1.5 rounded-md transition-all duration-150',
                            note.pinned ? 'text-[var(--color-phosphor-400,#33f7ff)] bg-[var(--color-phosphor-500,#00f5ff)]/10' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800',
                        )}
                        title={note.pinned ? 'Unpin' : 'Pin'}>
                        {note.pinned ? <Pin className="w-3.5 h-3.5 rotate-45" /> : <PinOff className="w-3.5 h-3.5" />}
                    </button>
                    <div className="flex items-center bg-slate-800 rounded-md border border-slate-700/60 ml-0.5">
                        <button type="button" onClick={() => setMode('edit')}
                            className={clsx('p-1.5 rounded-l-md transition-all duration-150', mode === 'edit' ? 'text-slate-100 bg-slate-700' : 'text-slate-500 hover:text-slate-300')}
                            title="Edit"><Pencil className="w-3 h-3" /></button>
                        <button type="button" onClick={() => setMode('preview')}
                            className={clsx('p-1.5 rounded-r-md transition-all duration-150', mode === 'preview' ? 'text-slate-100 bg-slate-700' : 'text-slate-500 hover:text-slate-300')}
                            title="Preview"><Eye className="w-3 h-3" /></button>
                    </div>
                    <button type="button" onClick={handleDelete}
                        className={clsx('p-1.5 rounded-md transition-all duration-150 ml-0.5', confirmDelete ? 'text-rose-400 bg-rose-500/10 hover:text-rose-300' : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800')}
                        title={confirmDelete ? 'Click again to confirm' : 'Delete'}>
                        <Trash2 className="w-3.5 h-3.5" />
                    </button>
                </div>
            </div>

            {/* Tags bar */}
            <div className="flex items-center gap-1.5 px-4 py-2 border-b border-slate-800/50 overflow-x-auto scrollbar-none">
                {tags.map(tag => (
                    <span key={tag} className="inline-flex items-center gap-1 px-1.5 py-0.5 rounded text-[10px] font-medium bg-slate-800 text-slate-400 border border-slate-700/50 flex-shrink-0">
                        {tag}
                        <button type="button" onClick={() => removeTag(tag)} className="hover:text-slate-200 transition-colors"><X className="w-2.5 h-2.5" /></button>
                    </span>
                ))}
                <input value={tagInput} onChange={e => setTagInput(e.target.value)} onKeyDown={handleTagKeyDown}
                    placeholder={tags.length === 0 ? 'add tags...' : '+'} className="bg-transparent text-[10px] text-slate-500 placeholder:text-slate-700 outline-none min-w-[40px] flex-shrink-0" />
            </div>

            {/* Content area */}
            <div className="flex-1 min-h-0 overflow-y-auto">
                {mode === 'edit' ? (
                    <textarea value={content} onChange={e => handleContentChange(e.target.value)} placeholder="Write something..."
                        className="w-full h-full px-4 py-3 bg-transparent text-sm text-slate-300 placeholder:text-slate-700 outline-none resize-none font-mono leading-relaxed" spellCheck={false} />
                ) : (
                    <div className="px-4 py-3 text-sm text-slate-300 prose prose-invert prose-sm max-w-none prose-headings:text-slate-200 prose-a:text-[var(--color-phosphor-400,#33f7ff)] prose-code:text-amber-300 prose-code:bg-slate-800 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-slate-950 prose-pre:border prose-pre:border-slate-700/50">
                        {content ? <Markdown remarkPlugins={[remarkGfm]}>{content}</Markdown> : <p className="text-slate-600 italic">Nothing here yet.</p>}
                    </div>
                )}
            </div>

            {/* Prompt actions */}
            {note.type === 'prompt' && (
                <PromptActions
                    content={content}
                    noteId={note.id}
                    onRefineStarted={() => {
                        setFormatState('pending');
                        startPolling(note.id);
                    }}
                />
            )}
        </div>
    );
}
