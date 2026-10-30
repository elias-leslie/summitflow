import { useState, useRef, useEffect, useCallback } from 'react';
import { useCreateNote, useUpdateNote, useDeleteNote } from './useNotes';
import type { Note } from './types';

export type SaveState = 'idle' | 'saving' | 'saved';
export type EditMode = 'edit' | 'preview';

interface UseNoteEditorStateOptions {
    /** A note without an id is an unsaved draft: the first edit creates it. */
    note: Note;
    onDeleted: () => void;
    onCreated?: (note: Note) => void;
}

type NoteChanges = { title?: string; content?: string; tags?: string[]; pinned?: boolean };
type DraftCreate = { queued: NoteChanges | null; detached: boolean; discard: boolean };

export interface NoteEditorState {
    pinned: boolean;
    title: string;
    setTitle: (v: string) => void;
    content: string;
    setContent: (v: string) => void;
    tags: string[];
    setTags: (v: string[]) => void;
    tagInput: string;
    setTagInput: (v: string) => void;
    mode: EditMode;
    setMode: (v: EditMode) => void;
    saveState: SaveState;
    setSaveState: (v: SaveState) => void;
    confirmDelete: boolean;
    autoFormatAttemptedRef: React.MutableRefObject<boolean>;
    mutateRef: React.MutableRefObject<ReturnType<typeof useUpdateNote>['mutate']>;
    save: (updates: NoteChanges) => void;
    handleTitleChange: (val: string) => void;
    handleContentChange: (val: string) => void;
    handleTagKeyDown: (e: React.KeyboardEvent<HTMLInputElement>) => void;
    removeTag: (tag: string) => void;
    togglePin: () => void;
    handleDelete: () => void;
}

export function useNoteEditorState({ note, onDeleted, onCreated }: UseNoteEditorStateOptions): NoteEditorState {
    const [pinned, setPinned] = useState(note.pinned);
    const [title, setTitle] = useState(note.title);
    const [content, setContent] = useState(note.content);
    const [tags, setTags] = useState<string[]>(note.tags);
    const [tagInput, setTagInput] = useState('');
    const [mode, setMode] = useState<EditMode>('edit');
    const [saveState, setSaveState] = useState<SaveState>('idle');
    const [confirmDelete, setConfirmDelete] = useState(false);

    const autoFormatAttemptedRef = useRef(false);
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const pendingRef = useRef<NoteChanges | null>(null);

    const createNote = useCreateNote();
    const updateNote = useUpdateNote();
    const deleteNote = useDeleteNote();
    const mutateRef = useRef(updateNote.mutate);
    mutateRef.current = updateNote.mutate;
    const createRef = useRef(createNote.mutateAsync);
    createRef.current = createNote.mutateAsync;
    const deleteRef = useRef(deleteNote.mutate);
    deleteRef.current = deleteNote.mutate;
    const onCreatedRef = useRef(onCreated);
    onCreatedRef.current = onCreated;

    // The saved id of the note being edited; empty until a draft is created.
    const idRef = useRef(note.id);
    const draftRef = useRef({ type: note.type, project_scope: note.project_scope });
    // The current draft's in-flight create. Leaving the draft detaches it, so its result
    // never lands on whatever note is open by then.
    const creatingRef = useRef<DraftCreate | null>(null);

    const detachCreate = (discard = false) => {
        if (!creatingRef.current) return;
        creatingRef.current.detached = true;
        creatingRef.current.discard = discard;
        creatingRef.current = null;
    };

    // A flush while leaving a draft (switch or unmount) creates it without selecting it again.
    const send = useCallback((data: NoteChanges, callbacks?: { onSuccess?: () => void; onError?: () => void }, leaving = false) => {
        if (idRef.current) {
            mutateRef.current({ noteId: idRef.current, data }, callbacks);
            return;
        }
        const inFlight = creatingRef.current;
        if (inFlight) {
            inFlight.queued = { ...inFlight.queued, ...data };
            callbacks?.onSuccess?.();
            return;
        }
        const create: DraftCreate = { queued: null, detached: leaving, discard: false };
        if (!leaving) creatingRef.current = create;
        // mutateAsync settles after unmount too, unlike per-call mutate callbacks.
        createRef.current({ title: '', ...draftRef.current, ...data }).then((created) => {
            if (creatingRef.current === create) creatingRef.current = null;
            if (create.discard) { deleteRef.current(created.id); return; }
            callbacks?.onSuccess?.();
            if (create.queued) mutateRef.current({ noteId: created.id, data: create.queued });
            if (create.detached) return;
            idRef.current = created.id;
            onCreatedRef.current?.(created);
        }, () => {
            // Edits queued behind a failed create are older than what the next save sends.
            if (creatingRef.current === create) creatingRef.current = null;
            callbacks?.onError?.();
        });
    }, []);

    // Reset state on note switch. Every New click selects a fresh draft object, so key drafts by object.
    const switchKey: string | Note = note.id || note;
    const prevKeyRef = useRef(switchKey);
    useEffect(() => {
        if (prevKeyRef.current === switchKey) return;
        prevKeyRef.current = switchKey;
        // A draft that was just created is the same note: keep what is on screen.
        if (note.id && note.id === idRef.current) return;
        if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
        if (pendingRef.current) { send(pendingRef.current, undefined, true); pendingRef.current = null; }
        detachCreate();
        idRef.current = note.id;
        draftRef.current = { type: note.type, project_scope: note.project_scope };
        setPinned(note.pinned);
        setTitle(note.title);
        setContent(note.content);
        setTags(note.tags);
        setTagInput('');
        setSaveState('idle');
        setConfirmDelete(false);
        autoFormatAttemptedRef.current = false;
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [switchKey]);

    // Flush pending save on unmount
    useEffect(() => {
        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
            if (pendingRef.current) send(pendingRef.current, undefined, true);
            detachCreate();
        };
    }, [send]);

    const save = useCallback((updates: NoteChanges) => {
        if (debounceRef.current) clearTimeout(debounceRef.current);
        // Merge into the unsent save: a title typed just before the body must not be dropped.
        const data = { ...pendingRef.current, ...updates };
        pendingRef.current = data;
        debounceRef.current = setTimeout(() => {
            pendingRef.current = null;
            setSaveState('saving');
            send(data, {
                onSuccess: () => { setSaveState('saved'); setTimeout(() => setSaveState('idle'), 1500); },
                onError: () => setSaveState('idle'),
            });
        }, 500);
    }, [send]);

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
            if (tag && !tags.includes(tag)) {
                const next = [...tags, tag];
                setTags(next);
                save({ tags: next });
            }
            setTagInput('');
        }
        if (e.key === 'Backspace' && !tagInput && tags.length > 0) {
            const next = tags.slice(0, -1);
            setTags(next);
            save({ tags: next });
        }
    };

    const removeTag = (tag: string) => {
        const next = tags.filter(t => t !== tag);
        setTags(next);
        save({ tags: next });
    };

    const togglePin = () => {
        const next = !pinned;
        setPinned(next);
        save({ pinned: next });
    };

    const handleDelete = () => {
        const discardDraft = () => {
            if (debounceRef.current) { clearTimeout(debounceRef.current); debounceRef.current = null; }
            pendingRef.current = null;
            detachCreate(true);
            onDeleted();
        };
        // Nothing typed or saved yet: discarding the draft needs no confirmation.
        if (!idRef.current && !creatingRef.current && !pendingRef.current) { discardDraft(); return; }
        if (!confirmDelete) {
            setConfirmDelete(true);
            setTimeout(() => setConfirmDelete(false), 3000);
            return;
        }
        if (idRef.current) deleteNote.mutate(idRef.current, { onSuccess: onDeleted });
        else discardDraft();
    };

    return {
        pinned,
        title, setTitle, content, setContent, tags, setTags,
        tagInput, setTagInput, mode, setMode,
        saveState, setSaveState, confirmDelete,
        autoFormatAttemptedRef, mutateRef,
        save, handleTitleChange, handleContentChange,
        handleTagKeyDown, removeTag, togglePin, handleDelete,
    };
}
