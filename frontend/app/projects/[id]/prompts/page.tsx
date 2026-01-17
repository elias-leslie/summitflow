'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import clsx from 'clsx'
import {
  AlertCircle,
  Brain,
  Check,
  ChevronRight,
  Download,
  FileCode,
  FlaskConical,
  RefreshCw,
  Sparkles,
  Upload,
  Wrench,
  X,
} from 'lucide-react'
import { useParams } from 'next/navigation'
import { useMemo, useRef, useState } from 'react'
import { PromptEditor } from '@/components/prompts/PromptEditor'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import {
  exportPrompts,
  fetchPrompts,
  importPrompts,
  type Prompt,
  type PromptCategory,
  type PromptUpdate,
} from '@/lib/api'

interface TabConfig {
  id: PromptCategory
  label: string
  icon: React.ElementType
  color: string
}

const tabs: TabConfig[] = [
  { id: 'spec', label: 'Spec Pipeline', icon: FileCode, color: 'emerald' },
  { id: 'recovery', label: 'Recovery', icon: Wrench, color: 'orange' },
  { id: 'qa', label: 'QA', icon: FlaskConical, color: 'cyan' },
  { id: 'extraction', label: 'Extraction', icon: Brain, color: 'purple' },
]

function PromptsPageSkeleton() {
  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        {tabs.map((_, i) => (
          <Skeleton key={i} className="h-10 w-32" />
        ))}
      </div>
      <div className="space-y-3">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 w-full rounded-lg" />
        ))}
      </div>
    </div>
  )
}

function PromptCard({
  prompt,
  onClick,
}: {
  prompt: Prompt
  onClick: () => void
}) {
  const formatPromptType = (type: string) => {
    return type
      .split('_')
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(' ')
  }

  return (
    <button
      onClick={onClick}
      className={clsx(
        'w-full text-left p-4 rounded-lg border transition-all duration-200',
        'bg-slate-900/50 border-slate-700',
        'hover:border-slate-500 hover:bg-slate-800/50',
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <h3 className="text-sm font-medium text-white truncate">
              {formatPromptType(prompt.prompt_type)}
            </h3>
            {prompt.is_default ? (
              <Badge
                variant="outline"
                className="text-slate-500 border-slate-600 text-xs"
              >
                Default
              </Badge>
            ) : (
              <Badge className="bg-phosphor-500/20 text-phosphor-400 border-phosphor-500/30 text-xs">
                Custom
              </Badge>
            )}
          </div>
          <p className="text-xs text-slate-500 line-clamp-2">
            {prompt.prompt_text.slice(0, 150)}...
          </p>
        </div>
        <div className="flex items-center gap-4 flex-shrink-0">
          {prompt.thinking_budget > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Sparkles className="w-3.5 h-3.5 text-amber-400" />
              <span>{(prompt.thinking_budget / 1000).toFixed(0)}k</span>
            </div>
          )}
          {prompt.tools_enabled.length > 0 && (
            <div className="flex items-center gap-1.5 text-xs text-slate-400">
              <Wrench className="w-3.5 h-3.5" />
              <span>{prompt.tools_enabled.length}</span>
            </div>
          )}
          <ChevronRight className="w-4 h-4 text-slate-500" />
        </div>
      </div>
    </button>
  )
}

export default function PromptsPage() {
  const params = useParams()
  const projectId = params.id as string
  const queryClient = useQueryClient()
  const fileInputRef = useRef<HTMLInputElement>(null)

  const [activeTab, setActiveTab] = useState<PromptCategory>('spec')
  const [selectedPrompt, setSelectedPrompt] = useState<Prompt | null>(null)
  const [importPreview, setImportPreview] = useState<PromptUpdate[] | null>(
    null,
  )
  const [toast, setToast] = useState<{
    type: 'success' | 'error'
    message: string
  } | null>(null)

  const {
    data: prompts = [],
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ['prompts', projectId],
    queryFn: () => fetchPrompts(projectId),
  })

  // Export mutation
  const exportMutation = useMutation({
    mutationFn: () => exportPrompts(projectId),
    onSuccess: (data) => {
      const blob = new Blob([JSON.stringify(data, null, 2)], {
        type: 'application/json',
      })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = `prompts-${projectId}-${new Date().toISOString().split('T')[0]}.json`
      document.body.appendChild(a)
      a.click()
      document.body.removeChild(a)
      URL.revokeObjectURL(url)
      showToast('success', 'Prompts exported successfully')
    },
    onError: () => {
      showToast('error', 'Failed to export prompts')
    },
  })

  // Import mutation
  const importMutation = useMutation({
    mutationFn: (promptsToImport: PromptUpdate[]) =>
      importPrompts(projectId, promptsToImport),
    onSuccess: (result) => {
      queryClient.invalidateQueries({ queryKey: ['prompts', projectId] })
      setImportPreview(null)
      showToast(
        'success',
        `Imported ${result.imported} prompts, updated ${result.updated}`,
      )
    },
    onError: () => {
      showToast('error', 'Failed to import prompts')
    },
  })

  const showToast = (type: 'success' | 'error', message: string) => {
    setToast({ type, message })
    setTimeout(() => setToast(null), 3000)
  }

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const data = JSON.parse(event.target?.result as string)
        const promptsData = data.prompts || data
        if (Array.isArray(promptsData)) {
          setImportPreview(promptsData)
        } else {
          showToast('error', 'Invalid file format - expected prompts array')
        }
      } catch {
        showToast('error', 'Failed to parse JSON file')
      }
    }
    reader.readAsText(file)
    e.target.value = ''
  }

  const groupedPrompts = useMemo(() => {
    const groups: Record<PromptCategory, Prompt[]> = {
      spec: [],
      recovery: [],
      qa: [],
      extraction: [],
    }
    for (const prompt of prompts) {
      const cat = prompt.category as PromptCategory
      if (groups[cat]) {
        groups[cat].push(prompt)
      }
    }
    return groups
  }, [prompts])

  const currentPrompts = groupedPrompts[activeTab] || []

  if (isLoading) {
    return (
      <div className="h-full overflow-auto p-4">
        <PromptsPageSkeleton />
      </div>
    )
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-4">
      {/* Category Tabs */}
      <div className="flex items-center gap-2 flex-wrap">
        {tabs.map((tab) => {
          const Icon = tab.icon
          const isActive = activeTab === tab.id
          const count = groupedPrompts[tab.id].length

          return (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={clsx(
                'flex items-center gap-2 px-4 py-2 rounded-lg text-sm font-medium transition-all',
                isActive
                  ? `bg-${tab.color}-500/15 text-${tab.color}-400`
                  : 'text-slate-500 hover:text-slate-300 hover:bg-slate-800',
              )}
              style={
                isActive
                  ? {
                      backgroundColor: `rgb(var(--${tab.color}-500) / 0.15)`,
                      color: `rgb(var(--${tab.color}-400))`,
                    }
                  : undefined
              }
            >
              <Icon className="w-4 h-4" />
              <span>{tab.label}</span>
              {count > 0 && (
                <span
                  className={clsx(
                    'px-1.5 py-0.5 rounded text-xs',
                    isActive ? 'bg-white/10' : 'bg-slate-700',
                  )}
                >
                  {count}
                </span>
              )}
            </button>
          )
        })}

        <div className="flex-1" />

        <input
          ref={fileInputRef}
          type="file"
          accept=".json"
          onChange={handleFileSelect}
          className="hidden"
        />

        <Button
          variant="outline"
          size="sm"
          onClick={() => fileInputRef.current?.click()}
        >
          <Upload className="h-4 w-4 mr-1.5" />
          Import
        </Button>

        <Button
          variant="outline"
          size="sm"
          onClick={() => exportMutation.mutate()}
          disabled={exportMutation.isPending}
        >
          {exportMutation.isPending ? (
            <div className="h-4 w-4 border-2 border-slate-400/30 border-t-slate-400 rounded-full animate-spin mr-1.5" />
          ) : (
            <Download className="h-4 w-4 mr-1.5" />
          )}
          Export
        </Button>

        <Button variant="outline" size="sm" onClick={() => refetch()}>
          <RefreshCw className="h-4 w-4 mr-1.5" />
          Refresh
        </Button>
      </div>

      {/* Results count */}
      <div className="text-sm text-slate-500">
        {currentPrompts.length > 0
          ? `${currentPrompts.length} prompt${currentPrompts.length !== 1 ? 's' : ''} in ${
              tabs.find((t) => t.id === activeTab)?.label
            }`
          : `No prompts in ${tabs.find((t) => t.id === activeTab)?.label}`}
      </div>

      {/* Prompts List */}
      <div className="space-y-3">
        {currentPrompts.map((prompt) => (
          <PromptCard
            key={prompt.prompt_type}
            prompt={prompt}
            onClick={() => setSelectedPrompt(prompt)}
          />
        ))}
      </div>

      {/* Prompt Editor Modal */}
      {selectedPrompt && (
        <PromptEditor
          prompt={selectedPrompt}
          projectId={projectId}
          onClose={() => setSelectedPrompt(null)}
        />
      )}

      {/* Import Preview Modal */}
      {importPreview && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-4">
          <div className="bg-slate-900 rounded-lg border border-slate-700 max-w-2xl w-full max-h-[80vh] flex flex-col">
            <div className="p-4 border-b border-slate-700 flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">
                Import Prompts
              </h2>
              <button
                onClick={() => setImportPreview(null)}
                className="text-slate-400 hover:text-white p-1"
              >
                <X className="w-5 h-5" />
              </button>
            </div>
            <div className="flex-1 overflow-auto p-4">
              <p className="text-sm text-slate-400 mb-4">
                The following {importPreview.length} prompt(s) will be imported:
              </p>
              <div className="space-y-2">
                {importPreview.map((p, i) => (
                  <div
                    key={i}
                    className="p-3 bg-slate-800 rounded border border-slate-700"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-sm font-medium text-white">
                        {p.prompt_text
                          ? (p as { prompt_type?: string }).prompt_type ||
                            `Prompt ${i + 1}`
                          : `Prompt ${i + 1}`}
                      </span>
                      <Badge variant="outline" className="text-xs">
                        {p.category || 'extraction'}
                      </Badge>
                    </div>
                    <p className="text-xs text-slate-500 mt-1 line-clamp-2">
                      {p.prompt_text?.slice(0, 100)}...
                    </p>
                  </div>
                ))}
              </div>
            </div>
            <div className="p-4 border-t border-slate-700 flex justify-end gap-2">
              <Button variant="outline" onClick={() => setImportPreview(null)}>
                Cancel
              </Button>
              <Button
                onClick={() => importMutation.mutate(importPreview)}
                disabled={importMutation.isPending}
              >
                {importMutation.isPending ? (
                  <div className="h-4 w-4 border-2 border-white/30 border-t-white rounded-full animate-spin mr-1.5" />
                ) : (
                  <Upload className="w-4 h-4 mr-1.5" />
                )}
                Import {importPreview.length} Prompts
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Toast Notification */}
      {toast && (
        <div
          className={clsx(
            'fixed bottom-4 right-4 z-50 flex items-center gap-2 px-4 py-3 rounded-lg shadow-lg',
            toast.type === 'success'
              ? 'bg-phosphor-500/20 border border-phosphor-500/30 text-phosphor-400'
              : 'bg-rose-500/20 border border-rose-500/30 text-rose-400',
          )}
        >
          {toast.type === 'success' ? (
            <Check className="w-4 h-4" />
          ) : (
            <AlertCircle className="w-4 h-4" />
          )}
          <span className="text-sm">{toast.message}</span>
        </div>
      )}
    </div>
  )
}
