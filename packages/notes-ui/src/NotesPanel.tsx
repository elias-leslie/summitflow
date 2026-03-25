import { useState } from 'react';
import { StickyNote, ExternalLink, ChevronDown } from 'lucide-react';
import clsx from 'clsx';
import { useNotesContext } from './NotesProvider';
import { useNotesList } from './useNotes';
import { NotesList } from './NotesList';
import { NoteEditor } from './NoteEditor';
import type { Note } from './types';

interface NotesPanelProps {
    onPopOut?: () => void;
}

export function NotesPanel({ onPopOut }: NotesPanelProps) {
    const { projectScope } = useNotesContext();
    const [activeTab, setActiveTab] = useState<'note' | 'prompt'>('note');
    const [scopeFilter, setScopeFilter] = useState<string | undefined>(projectScope);
    const [selectedNote, setSelectedNote] = useState<Note | null>(null);
    const [showScopeMenu, setShowScopeMenu] = useState(false);

    // Scopes for dropdown
    const { data: allNotes } = useNotesList({ limit: 200 });
    const scopes = Array.from(new Set(allNotes?.items.map(n => n.project_scope) ?? [])).sort();
    if (!scopes.includes(projectScope)) scopes.push(projectScope);

    return (
        <div className="flex flex-col flex-1 min-h-0 bg-slate-900">
            {/* ── Header bar ── */}
            <div className="flex items-center justify-between px-3 py-2.5 border-b border-slate-700/50 flex-shrink-0 bg-slate-950/60">
                <div className="flex items-center gap-2">
                    <StickyNote className="w-3.5 h-3.5 text-[var(--color-phosphor-400,#33f7ff)]" />
                    <span className="text-xs font-semibold text-slate-200 tracking-wide" style={{ fontFamily: 'var(--font-display, inherit)' }}>Notes</span>
                </div>

                <div className="flex items-center gap-1.5">
                    {/* Tab switcher */}
                    <div className="flex items-center bg-slate-800/80 rounded-md border border-slate-700/50 mr-1">
                        <button
                            type="button"
                            onClick={() => { setActiveTab('note'); setSelectedNote(null); }}
                            className={clsx(
                                'px-2.5 py-1 text-[10px] font-medium rounded-l-md transition-colors',
                                activeTab === 'note'
                                    ? 'text-slate-200 bg-slate-700'
                                    : 'text-slate-500 hover:text-slate-400',
                            )}
                        >
                            Notes
                        </button>
                        <button
                            type="button"
                            onClick={() => { setActiveTab('prompt'); setSelectedNote(null); }}
                            className={clsx(
                                'px-2.5 py-1 text-[10px] font-medium rounded-r-md transition-colors',
                                activeTab === 'prompt'
                                    ? 'text-amber-300 bg-slate-700'
                                    : 'text-slate-500 hover:text-slate-400',
                            )}
                        >
                            Prompts
                        </button>
                    </div>

                    {/* Scope selector */}
                    <div className="relative">
                        <button
                            type="button"
                            onClick={() => setShowScopeMenu(v => !v)}
                            className="flex items-center gap-1 px-2 py-1 text-[10px] font-medium text-slate-400 hover:text-slate-300 bg-slate-800/50 rounded border border-slate-700/50 transition-colors"
                        >
                            {scopeFilter ?? 'All'}
                            <ChevronDown className="w-2.5 h-2.5" />
                        </button>
                        {showScopeMenu && (
                            <>
                                <div className="fixed inset-0 z-[101]" onClick={() => setShowScopeMenu(false)} />
                                <div className="absolute right-0 top-full mt-1 w-36 bg-slate-900 border border-slate-700 rounded-md shadow-xl z-[102] py-1 overflow-hidden">
                                    <button
                                        type="button"
                                        onClick={() => { setScopeFilter(undefined); setShowScopeMenu(false); }}
                                        className={clsx(
                                            'w-full text-left px-3 py-1.5 text-[11px] transition-colors',
                                            !scopeFilter ? 'text-[var(--color-phosphor-400,#33f7ff)] bg-slate-800/50' : 'text-slate-400 hover:text-slate-300 hover:bg-slate-800/30',
                                        )}
                                    >
                                        All Projects
                                    </button>
                                    {['global', ...scopes.filter(s => s !== 'global')].map(scope => (
                                        <button
                                            key={scope}
                                            type="button"
                                            onClick={() => { setScopeFilter(scope); setShowScopeMenu(false); }}
                                            className={clsx(
                                                'w-full text-left px-3 py-1.5 text-[11px] transition-colors',
                                                scopeFilter === scope ? 'text-[var(--color-phosphor-400,#33f7ff)] bg-slate-800/50' : 'text-slate-400 hover:text-slate-300 hover:bg-slate-800/30',
                                            )}
                                        >
                                            {scope}
                                        </button>
                                    ))}
                                </div>
                            </>
                        )}
                    </div>

                    {/* Pop-out button */}
                    {onPopOut && (
                        <button
                            type="button"
                            onClick={onPopOut}
                            className="p-1 text-slate-500 hover:text-[var(--color-phosphor-400,#33f7ff)] rounded transition-colors"
                            title="Open in separate window"
                        >
                            <ExternalLink className="w-3.5 h-3.5" />
                        </button>
                    )}
                </div>
            </div>

            {/* ── Body: list + editor ── */}
            <div className="flex flex-1 min-h-0 overflow-hidden bg-slate-900">
                <NotesList
                    activeTab={activeTab}
                    scopeFilter={scopeFilter}
                    selectedId={selectedNote?.id ?? null}
                    onSelect={setSelectedNote}
                />
                <div className="flex-1 min-w-0 bg-slate-900">
                    {selectedNote ? (
                        <NoteEditor
                            note={selectedNote}
                            onDeleted={() => setSelectedNote(null)}
                        />
                    ) : (
                        <div className="flex items-center justify-center h-full bg-slate-900">
                            <div className="text-center space-y-3">
                                <div className="relative mx-auto w-12 h-12 flex items-center justify-center">
                                    <div className="absolute inset-0 rounded-xl bg-[var(--color-phosphor-500,#00f5ff)]/5 border border-[var(--color-phosphor-500,#00f5ff)]/10" />
                                    <StickyNote className="w-5 h-5 text-slate-600 relative" />
                                </div>
                                <div>
                                    <p className="text-xs text-slate-500 font-medium">Select or create a {activeTab}</p>
                                    <p className="text-[10px] text-slate-600 mt-1">Use the sidebar to browse, or press + to start fresh</p>
                                </div>
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
