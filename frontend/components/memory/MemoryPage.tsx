'use client';

import { useState, useEffect } from 'react';
import { Brain, ChevronDown, Activity, Clock, FileText, Lightbulb, BookOpen, X, Sparkles, Shield } from 'lucide-react';
import { clsx } from 'clsx';
import { AnimatePresence, motion } from 'motion/react';
import { Tabs, TabsList, TabsTrigger, TabsContent } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';
import { fetchProjects, type Project } from '@/lib/api';
import { BulkActionsBar } from './BulkActionsBar';
import { formatAge, formatTokens } from '@/lib/formatters/memory-formatters';
import { ObservationRow, type Observation, PatternRow, type Pattern, DiaryRow, type DiaryEntry } from './rows';
import { SearchBar } from './SearchBar';
import { FilterPanel, type SearchFilters } from './FilterPanel';
import { useMemorySearch } from '@/lib/hooks/useMemorySearch';
import { HealthTab } from './HealthTab';
import { MetricsSection, MetricCard, type MemoryStats } from './MetricsSection';
import { Pagination, ITEMS_PER_PAGE } from './Pagination';

// Main Memory Page Component
export default function MemoryPage() {
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [patterns, setPatterns] = useState<Pattern[]>([]);
  const [diaryEntries, setDiaryEntries] = useState<DiaryEntry[]>([]);
  const [projects, setProjects] = useState<Project[]>([]);
  const [selectedProject, setSelectedProject] = useState<string | null>(null);
  const [activeTab, setActiveTab] = useState('observations');
  const [loading, setLoading] = useState(true);
  const [projectDropdownOpen, setProjectDropdownOpen] = useState(false);

  // Pagination state
  const [observationsPage, setObservationsPage] = useState(1);
  const [patternsPage, setPatternsPage] = useState(1);
  const [diaryPage, setDiaryPage] = useState(1);

  // Total counts from API
  const [observationsTotal, setObservationsTotal] = useState(0);
  const [patternsTotal, setPatternsTotal] = useState(0);
  const [diaryTotal, setDiaryTotal] = useState(0);

  // Search state
  const [isSearching, setIsSearching] = useState(false);
  const [searchQuery, setSearchQuery] = useState('');
  const [showFilters, setShowFilters] = useState(false);
  const [filters, setFilters] = useState<SearchFilters>({
    type: 'all',
    concepts: [],
    useSemantic: false,
  });
  const { results, total: searchTotal, usedSemantic, isLoading: searchLoading, error: searchError, search, clear: clearSearch } = useMemorySearch();

  // Fetch data
  useEffect(() => {
    const fetchData = async () => {
      try {
        setLoading(true);

        // Fetch stats (filtered by project if selected)
        const statsUrl = selectedProject
          ? `/api/memory/stats?project_id=${selectedProject}`
          : '/api/memory/stats';
        const statsRes = await fetch(statsUrl);
        if (statsRes.ok) {
          const statsData = await statsRes.json();
          setStats(statsData);
        }

        // Fetch observations (global or filtered) - use offset-based pagination
        const obsOffset = (observationsPage - 1) * ITEMS_PER_PAGE;
        const obsUrl = selectedProject
          ? `/api/observations?project_id=${selectedProject}&limit=${ITEMS_PER_PAGE}&offset=${obsOffset}`
          : `/api/observations?limit=${ITEMS_PER_PAGE}&offset=${obsOffset}`;
        const obsRes = await fetch(obsUrl);
        if (obsRes.ok) {
          const obsData = await obsRes.json();
          setObservations(obsData.items || []);
          setObservationsTotal(obsData.total || 0);
        }

        // Fetch patterns (global or filtered)
        const patOffset = (patternsPage - 1) * ITEMS_PER_PAGE;
        const patUrl = selectedProject
          ? `/api/patterns?project_id=${selectedProject}&limit=${ITEMS_PER_PAGE}&offset=${patOffset}`
          : `/api/patterns?limit=${ITEMS_PER_PAGE}&offset=${patOffset}`;
        const patRes = await fetch(patUrl);
        if (patRes.ok) {
          const patData = await patRes.json();
          setPatterns(patData.items || []);
          setPatternsTotal(patData.total || 0);
        }

        // Fetch diary entries (global or filtered)
        const diaryOffset = (diaryPage - 1) * ITEMS_PER_PAGE;
        const diaryUrl = selectedProject
          ? `/api/diary?project_id=${selectedProject}&limit=${ITEMS_PER_PAGE}&offset=${diaryOffset}`
          : `/api/diary?limit=${ITEMS_PER_PAGE}&offset=${diaryOffset}`;
        const diaryRes = await fetch(diaryUrl);
        if (diaryRes.ok) {
          const diaryData = await diaryRes.json();
          setDiaryEntries(diaryData.items || []);
          setDiaryTotal(diaryData.total || 0);
        }

        // Fetch projects for filter
        const projectsData = await fetchProjects();
        setProjects(projectsData);
      } catch (error) {
        console.error('Failed to fetch memory data:', error);
      } finally {
        setLoading(false);
      }
    };

    fetchData();
  }, [selectedProject, observationsPage, patternsPage, diaryPage]);

  const handleApprovePattern = async (patternId: string) => {
    try {
      const res = await fetch('/api/patterns/bulk-approve', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern_ids: [patternId], reason: 'user-approved' }),
      });
      if (res.ok) {
        setPatterns(patterns.map(p => p.id === patternId ? { ...p, status: 'approved' } : p));
      }
    } catch (error) {
      console.error('Failed to approve pattern:', error);
    }
  };

  const handleRejectPattern = async (patternId: string) => {
    try {
      const res = await fetch('/api/patterns/bulk-reject', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ pattern_ids: [patternId], reason: 'user-rejected' }),
      });
      if (res.ok) {
        setPatterns(patterns.map(p => p.id === patternId ? { ...p, status: 'rejected' } : p));
      }
    } catch (error) {
      console.error('Failed to reject pattern:', error);
    }
  };

  const pendingPatterns = patterns.filter(p => p.status === 'pending');

  // Reset pagination when project changes
  useEffect(() => {
    setObservationsPage(1);
    setPatternsPage(1);
    setDiaryPage(1);
  }, [selectedProject]);

  // Handle search
  const handleSearch = async (query: string) => {
    if (!selectedProject) {
      // Search requires a project context
      return;
    }
    setSearchQuery(query);
    setIsSearching(true);
    await search({
      q: query,
      project_id: selectedProject,
      type: filters.type,
      concepts: filters.concepts,
      use_semantic: filters.useSemantic,
    });
  };

  // Clear search and return to default view
  const handleClearSearch = () => {
    setIsSearching(false);
    setSearchQuery('');
    clearSearch();
  };

  // Group search results by entity type
  const searchResultsByType = {
    observations: results.filter(r => r.entity_type === 'observation'),
    patterns: results.filter(r => r.entity_type === 'pattern'),
    diary: results.filter(r => r.entity_type === 'diary'),
    user_prompts: results.filter(r => r.entity_type === 'user_prompt'),
  };

  return (
    <div className="min-h-screen bg-slate-950 p-8">
      <div className="max-w-[1400px] mx-auto">
        {/* Header */}
        <header className="flex items-center justify-between mb-8">
          <div className="flex items-center gap-4">
            <Brain className="w-7 h-7 text-outrun-500" />
            <h1 className="text-[28px] font-semibold text-slate-100 tracking-tight">Memory</h1>
          </div>

          {/* Project Filter Dropdown */}
          <div className="relative">
            <button
              onClick={() => setProjectDropdownOpen(!projectDropdownOpen)}
              className="flex items-center gap-2 px-4 py-2 bg-slate-800/50 border border-slate-700/50 rounded-lg hover:border-slate-600 transition-colors"
            >
              <span className="text-sm text-slate-400">Project:</span>
              <span className="text-sm font-medium text-slate-200">
                {selectedProject ? projects.find(p => p.id === selectedProject)?.name || selectedProject : 'All Projects'}
              </span>
              <ChevronDown className="w-4 h-4 text-slate-500" />
            </button>

            <AnimatePresence>
              {projectDropdownOpen && (
                <motion.div
                  initial={{ opacity: 0, y: -4 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, y: -4 }}
                  className="absolute right-0 top-full mt-2 w-56 bg-slate-800 border border-slate-700 rounded-lg shadow-xl z-50 overflow-hidden"
                >
                  <button
                    onClick={() => { setSelectedProject(null); setProjectDropdownOpen(false); }}
                    className={clsx(
                      'w-full px-4 py-2.5 text-left text-sm hover:bg-slate-700/50 transition-colors',
                      !selectedProject ? 'text-outrun-400 bg-outrun-500/10' : 'text-slate-300'
                    )}
                  >
                    All Projects
                  </button>
                  {projects.map((project) => (
                    <button
                      key={project.id}
                      onClick={() => { setSelectedProject(project.id); setProjectDropdownOpen(false); }}
                      className={clsx(
                        'w-full px-4 py-2.5 text-left text-sm hover:bg-slate-700/50 transition-colors',
                        selectedProject === project.id ? 'text-outrun-400 bg-outrun-500/10' : 'text-slate-300'
                      )}
                    >
                      {project.name}
                    </button>
                  ))}
                </motion.div>
              )}
            </AnimatePresence>
          </div>
        </header>

        {/* Search Section */}
        <div className="mb-8 space-y-4">
          <div className="flex items-center gap-4">
            <SearchBar
              onSearch={handleSearch}
              isLoading={searchLoading}
              placeholder={selectedProject ? 'Search observations, patterns, diary...' : 'Select a project to search'}
            />
            <button
              onClick={() => setShowFilters(!showFilters)}
              className={clsx(
                'px-3 py-2.5 rounded-lg text-sm font-medium transition-colors',
                showFilters
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                  : 'bg-slate-800/50 text-slate-400 border border-slate-700/50 hover:border-slate-600'
              )}
            >
              Filters
            </button>
          </div>

          {/* Collapsible Filter Panel */}
          <AnimatePresence>
            {showFilters && (
              <motion.div
                initial={{ opacity: 0, height: 0 }}
                animate={{ opacity: 1, height: 'auto' }}
                exit={{ opacity: 0, height: 0 }}
                className="overflow-hidden"
              >
                <div className="p-4 bg-slate-800/30 border border-slate-700/50 rounded-lg">
                  <FilterPanel filters={filters} onChange={setFilters} />
                </div>
              </motion.div>
            )}
          </AnimatePresence>

          {/* Search Results Indicator */}
          {isSearching && (
            <div className="flex items-center justify-between px-4 py-3 bg-blue-500/10 border border-blue-500/20 rounded-lg">
              <div className="flex items-center gap-3">
                {usedSemantic && (
                  <span className="flex items-center gap-1 text-xs text-blue-400">
                    <Sparkles className="w-3 h-3" />
                    Semantic
                  </span>
                )}
                <span className="text-sm text-slate-300">
                  Showing <span className="font-medium text-blue-400">{searchTotal}</span> results for &quot;{searchQuery}&quot;
                </span>
              </div>
              <button
                onClick={handleClearSearch}
                className="flex items-center gap-1 px-2 py-1 text-xs text-slate-400 hover:text-slate-200 transition-colors"
              >
                <X className="w-3 h-3" />
                Clear Search
              </button>
            </div>
          )}

          {/* Search Error */}
          {searchError && (
            <div className="px-4 py-3 bg-rose-500/10 border border-rose-500/20 rounded-lg text-sm text-rose-400">
              {searchError}
            </div>
          )}
        </div>

        {/* Metrics Grid */}
        <div className="grid grid-cols-4 gap-4 mb-8">
          <MetricCard
            label="Queue Depth"
            value={stats?.queue_depth ?? '-'}
            subtitle={stats ? `${stats.queue_pending} pending extraction` : undefined}
            accent="amber"
          />
          <MetricCard
            label="Observations"
            value={stats?.observations_today ?? '-'}
            subtitle={stats ? `${stats.observation_success_rate}% extraction success` : undefined}
            accent="green"
          />
          <MetricCard
            label="Token Spend"
            value={stats ? formatTokens(stats.token_spend_24h) ?? '-' : '-'}
            subtitle="24h total"
            accent="blue"
          />
          <MetricCard
            label="System Health"
            value=""
            subtitle="Hook connected"
            accent="health"
            isHealth
            healthStatus={stats?.health ?? 'healthy'}
          />
        </div>

        {/* Lifecycle Status Section */}
        {stats?.lifecycle && (
          <div className="mb-8">
            <div className="flex items-center gap-2 mb-4">
              <Clock className="w-4 h-4 text-slate-400" />
              <h2 className="text-sm font-semibold uppercase tracking-wider text-slate-400">Lifecycle Status</h2>
            </div>
            <div className="grid grid-cols-5 gap-3">
              <MetricCard
                label="Failed Queue"
                value={stats.lifecycle.failed_queue_count}
                subtitle="Items failed"
                accent={stats.lifecycle.failed_queue_count > 0 ? 'amber' : 'green'}
              />
              <MetricCard
                label="Stuck Items"
                value={stats.lifecycle.stuck_queue_count}
                subtitle="> 1 hour processing"
                accent={stats.lifecycle.stuck_queue_count > 0 ? 'amber' : 'green'}
              />
              <MetricCard
                label="Unreflected"
                value={stats.lifecycle.unreflected_diary_count}
                subtitle="Diary entries"
                accent={stats.lifecycle.unreflected_diary_count > 5 ? 'amber' : 'green'}
              />
              <MetricCard
                label="Stale Patterns"
                value={stats.lifecycle.stale_patterns_count}
                subtitle="30+ days unused"
                accent={stats.lifecycle.stale_patterns_count > 3 ? 'amber' : 'green'}
              />
              <MetricCard
                label="Oldest Pending"
                value={formatAge(stats.lifecycle.oldest_pending_age_minutes)}
                subtitle="Queue age"
                accent={stats.lifecycle.oldest_pending_age_minutes && stats.lifecycle.oldest_pending_age_minutes > 30 ? 'amber' : 'green'}
              />
            </div>
            {/* Pattern status badges */}
            {Object.keys(stats.lifecycle.pattern_status_breakdown).length > 0 && (
              <div className="flex items-center gap-2 mt-3">
                <span className="text-xs text-slate-500">Patterns:</span>
                {Object.entries(stats.lifecycle.pattern_status_breakdown).map(([status, count]) => (
                  <Badge
                    key={status}
                    variant="secondary"
                    className={clsx(
                      'text-xs',
                      status === 'pending' && 'bg-amber-500/15 text-amber-400',
                      status === 'approved' && 'bg-blue-500/15 text-blue-400',
                      status === 'applied' && 'bg-emerald-500/15 text-emerald-400',
                      status === 'rejected' && 'bg-rose-500/15 text-rose-400'
                    )}
                  >
                    {status}: {count}
                  </Badge>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Tabs */}
        <Tabs value={activeTab} onValueChange={setActiveTab}>
          <TabsList className="border-slate-700/50 mb-6">
            <TabsTrigger value="observations" className="gap-2">
              <FileText className="w-4 h-4" />
              Observations
              <span className={clsx(
                'text-[11px] font-semibold px-2 py-0.5 rounded-full',
                activeTab === 'observations' ? 'bg-outrun-500/15 text-outrun-400' : 'bg-slate-700/50 text-slate-500'
              )}>
                {isSearching ? searchResultsByType.observations.length : observationsTotal}
              </span>
            </TabsTrigger>
            <TabsTrigger value="patterns" className="gap-2">
              <Lightbulb className="w-4 h-4" />
              Patterns
              <span className={clsx(
                'text-[11px] font-semibold px-2 py-0.5 rounded-full',
                activeTab === 'patterns' ? 'bg-outrun-500/15 text-outrun-400' : 'bg-slate-700/50 text-slate-500'
              )}>
                {isSearching ? searchResultsByType.patterns.length : patternsTotal}
              </span>
            </TabsTrigger>
            <TabsTrigger value="diary" className="gap-2">
              <BookOpen className="w-4 h-4" />
              Diary
              <span className={clsx(
                'text-[11px] font-semibold px-2 py-0.5 rounded-full',
                activeTab === 'diary' ? 'bg-outrun-500/15 text-outrun-400' : 'bg-slate-700/50 text-slate-500'
              )}>
                {isSearching ? searchResultsByType.diary.length : diaryTotal}
              </span>
            </TabsTrigger>
            <TabsTrigger value="health" className="gap-2">
              <Shield className="w-4 h-4" />
              Health
            </TabsTrigger>
          </TabsList>

          {/* Observations Tab */}
          <TabsContent value="observations">
            {isSearching ? (
              // Search Results View
              searchResultsByType.observations.length === 0 ? (
                <div className="text-center py-16 text-slate-500">
                  <FileText className="w-10 h-10 mx-auto mb-4 opacity-30" />
                  <h3 className="text-lg font-medium text-slate-400 mb-2">No matching observations</h3>
                  <p className="text-sm">Try different search terms or filters</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {searchResultsByType.observations.map((result) => (
                    <ObservationRow
                      key={result.id}
                      observation={{
                        id: result.id,
                        project_id: (result.data.project_id as string) || '',
                        session_id: (result.data.session_id as string) || '',
                        agent_type: (result.data.agent_type as string) || 'unknown',
                        observation_type: (result.data.observation_type as string) || 'pattern',
                        title: result.title || 'Untitled',
                        concepts: (result.data.concepts as string[]) || [],
                        subtitle: result.summary || undefined,
                        narrative: (result.data.narrative as string) || undefined,
                        facts: (result.data.facts as Record<string, unknown>) || undefined,
                        files_modified: (result.data.files_modified as string[]) || undefined,
                        discovery_tokens: (result.data.discovery_tokens as number) || 0,
                        created_at: result.created_at || new Date().toISOString(),
                      }}
                    />
                  ))}
                </div>
              )
            ) : loading ? (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <Activity className="w-5 h-5 animate-spin mr-2" />
                Loading observations...
              </div>
            ) : observationsTotal === 0 ? (
              <div className="text-center py-16 text-slate-500">
                <FileText className="w-10 h-10 mx-auto mb-4 opacity-30" />
                <h3 className="text-lg font-medium text-slate-400 mb-2">No observations yet</h3>
                <p className="text-sm">Observations will appear here as agents work</p>
              </div>
            ) : (
              <div>
                <div className="space-y-2">
                  {observations.map((obs) => (
                    <ObservationRow key={obs.id} observation={obs} />
                  ))}
                </div>
                <Pagination
                  currentPage={observationsPage}
                  totalItems={observationsTotal}
                  onPageChange={setObservationsPage}
                />
              </div>
            )}
          </TabsContent>

          {/* Patterns Tab */}
          <TabsContent value="patterns">
            {isSearching ? (
              // Search Results View
              searchResultsByType.patterns.length === 0 ? (
                <div className="text-center py-16 text-slate-500">
                  <Lightbulb className="w-10 h-10 mx-auto mb-4 opacity-30" />
                  <h3 className="text-lg font-medium text-slate-400 mb-2">No matching patterns</h3>
                  <p className="text-sm">Try different search terms or filters</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {searchResultsByType.patterns.map((result) => (
                    <PatternRow
                      key={result.id}
                      pattern={{
                        id: result.id,
                        project_id: (result.data.project_id as string) || '',
                        pattern_type: (result.data.pattern_type as string) || 'learned',
                        title: result.title || 'Untitled',
                        content: (result.data.content as string) || '',
                        rationale: result.summary || undefined,
                        action: (result.data.action as string) || 'add',
                        status: (result.data.status as string) || 'pending',
                        confidence: (result.data.confidence as number) || 0,
                        created_at: result.created_at || new Date().toISOString(),
                      }}
                      onApprove={handleApprovePattern}
                      onReject={handleRejectPattern}
                    />
                  ))}
                </div>
              )
            ) : loading ? (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <Activity className="w-5 h-5 animate-spin mr-2" />
                Loading patterns...
              </div>
            ) : patternsTotal === 0 ? (
              <div className="text-center py-16 text-slate-500">
                <Lightbulb className="w-10 h-10 mx-auto mb-4 opacity-30" />
                <h3 className="text-lg font-medium text-slate-400 mb-2">No pending patterns</h3>
                <p className="text-sm">Patterns will appear here for review after reflection</p>
              </div>
            ) : (
              <div>
                <BulkActionsBar
                  patterns={pendingPatterns}
                  onBulkApprove={async (patternIds) => {
                    try {
                      const res = await fetch('/api/patterns/bulk-approve', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ pattern_ids: patternIds, reason: 'bulk-approved' }),
                      });
                      if (res.ok) {
                        setPatterns(patterns.map(p =>
                          patternIds.includes(p.id) ? { ...p, status: 'approved' } : p
                        ));
                      }
                    } catch (error) {
                      console.error('Failed to bulk approve patterns:', error);
                    }
                  }}
                />
                <div className="space-y-2 mt-4">
                  {patterns.map((pattern) => (
                    <PatternRow
                      key={pattern.id}
                      pattern={pattern}
                      onApprove={handleApprovePattern}
                      onReject={handleRejectPattern}
                    />
                  ))}
                </div>
                <Pagination
                  currentPage={patternsPage}
                  totalItems={patternsTotal}
                  onPageChange={setPatternsPage}
                />
              </div>
            )}
          </TabsContent>

          {/* Diary Tab */}
          <TabsContent value="diary">
            {isSearching ? (
              // Search Results View
              searchResultsByType.diary.length === 0 ? (
                <div className="text-center py-16 text-slate-500">
                  <BookOpen className="w-10 h-10 mx-auto mb-4 opacity-30" />
                  <h3 className="text-lg font-medium text-slate-400 mb-2">No matching diary entries</h3>
                  <p className="text-sm">Try different search terms or filters</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {searchResultsByType.diary.map((result) => (
                    <DiaryRow
                      key={result.id}
                      entry={{
                        id: result.id,
                        project_id: (result.data.project_id as string) || '',
                        session_id: (result.data.session_id as string) || '',
                        task_id: (result.data.task_id as string | null) || null,
                        agent_type: (result.data.agent_type as string) || 'unknown',
                        duration_seconds: (result.data.duration_seconds as number | null) || null,
                        tokens_used: (result.data.tokens_used as number | null) || null,
                        discovery_tokens: (result.data.discovery_tokens as number | null) || null,
                        outcome: ((result.data.outcome as string) || 'neutral') as 'success' | 'failure' | 'partial' | 'neutral',
                        observation_type: (result.data.observation_type as string | null) || null,
                        concepts: (result.data.concepts as string[]) || [],
                        what_worked: (result.data.what_worked as string[] | null) || null,
                        what_failed: (result.data.what_failed as string[] | null) || null,
                        user_corrections: (result.data.user_corrections as string[] | null) || null,
                        created_at: result.created_at || new Date().toISOString(),
                      }}
                    />
                  ))}
                </div>
              )
            ) : loading ? (
              <div className="flex items-center justify-center py-16 text-slate-500">
                <Activity className="w-5 h-5 animate-spin mr-2" />
                Loading diary entries...
              </div>
            ) : diaryTotal === 0 ? (
              <div className="text-center py-16 text-slate-500">
                <BookOpen className="w-10 h-10 mx-auto mb-4 opacity-30" />
                <h3 className="text-lg font-medium text-slate-400 mb-2">No diary entries yet</h3>
                <p className="text-sm">Session summaries will appear here</p>
              </div>
            ) : (
              <div>
                <div className="space-y-2">
                  {diaryEntries.map((entry) => (
                    <DiaryRow key={entry.id} entry={entry} />
                  ))}
                </div>
                <Pagination
                  currentPage={diaryPage}
                  totalItems={diaryTotal}
                  onPageChange={setDiaryPage}
                />
              </div>
            )}
          </TabsContent>

          {/* Health Tab */}
          <TabsContent value="health">
            {selectedProject ? (
              <HealthTab projectId={selectedProject} />
            ) : (
              <div className="text-center py-16 text-slate-500">
                <Shield className="w-10 h-10 mx-auto mb-4 opacity-30" />
                <h3 className="text-lg font-medium text-slate-400 mb-2">Select a project</h3>
                <p className="text-sm">Choose a project from the dropdown to view health status</p>
              </div>
            )}
          </TabsContent>
        </Tabs>
      </div>
    </div>
  );
}
