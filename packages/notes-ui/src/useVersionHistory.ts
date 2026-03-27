import { useState, useCallback } from 'react';
import type { NoteVersion } from './types';

interface UseVersionHistoryOptions {
    noteId: string;
    api: {
        listVersions: (noteId: string) => Promise<NoteVersion[]>;
        revertToVersion: (noteId: string, versionId: string) => Promise<{ title: string; content: string; tags: string[] }>;
    };
    onReverted: (title: string, content: string, tags: string[]) => void;
}

export interface VersionHistoryState {
    showHistory: boolean;
    versions: NoteVersion[];
    loadingVersions: boolean;
    toggleHistory: () => void;
    revertToVersion: (versionId: string) => Promise<void>;
    setShowHistory: (v: boolean) => void;
}

export function useVersionHistory({ noteId, api, onReverted }: UseVersionHistoryOptions): VersionHistoryState {
    const [showHistory, setShowHistory] = useState(false);
    const [versions, setVersions] = useState<NoteVersion[]>([]);
    const [loadingVersions, setLoadingVersions] = useState(false);

    const loadVersions = useCallback(async () => {
        setLoadingVersions(true);
        try {
            const v = await api.listVersions(noteId);
            setVersions(v);
        } catch {}
        setLoadingVersions(false);
    }, [api, noteId]);

    const toggleHistory = useCallback(() => {
        if (!showHistory) loadVersions();
        setShowHistory(v => !v);
    }, [showHistory, loadVersions]);

    const revertToVersion = useCallback(async (versionId: string) => {
        try {
            const reverted = await api.revertToVersion(noteId, versionId);
            onReverted(reverted.title, reverted.content, reverted.tags);
            setShowHistory(false);
        } catch (err) {
            console.warn('Revert failed:', err);
        }
    }, [api, noteId, onReverted]);

    return { showHistory, versions, loadingVersions, toggleHistory, revertToVersion, setShowHistory };
}
