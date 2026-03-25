import { createContext, useContext, useMemo, type ReactNode } from 'react';
import { createNotesApi } from './api';
import type { NotesConfig } from './types';

interface NotesContextValue extends NotesConfig {
    api: ReturnType<typeof createNotesApi>;
    canInject: boolean;
}

const NotesContext = createContext<NotesContextValue | null>(null);

export function useNotesContext(): NotesContextValue {
    const ctx = useContext(NotesContext);
    if (!ctx) throw new Error('useNotesContext must be used within NotesProvider');
    return ctx;
}

interface NotesProviderProps extends NotesConfig {
    children: ReactNode;
}

export function NotesProvider({ apiPrefix, projectScope, onInject, children }: NotesProviderProps) {
    const value = useMemo<NotesContextValue>(() => ({
        apiPrefix,
        projectScope,
        onInject,
        canInject: typeof onInject === 'function',
        api: createNotesApi(apiPrefix),
    }), [apiPrefix, projectScope, onInject]);

    return <NotesContext.Provider value={value}>{children}</NotesContext.Provider>;
}
