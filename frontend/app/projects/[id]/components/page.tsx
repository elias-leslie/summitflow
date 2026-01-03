"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Search,
  RefreshCw,
  Plus,
} from "lucide-react";

import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Select, SelectTrigger, SelectValue, SelectContent, SelectItem } from "@/components/ui/select";
import { ComponentList } from "@/components/tdd-components/ComponentList";
import { CapabilityDrawer } from "@/components/tdd-components/CapabilityDrawer";
import { BuildProgress } from "@/components/tdd-components/BuildProgress";
import { CreateComponentModal } from "@/components/tdd-components/CreateComponentModal";
import { ComponentSuggestions } from "@/components/tdd-components/ComponentSuggestions";
import {
  fetchTddComponents,
  fetchTddCapabilities,
  type TddCapability,
} from "@/lib/api";

function ComponentsPageSkeleton() {
  return (
    <div className="space-y-4">
      <div className="rounded-lg border border-slate-700 bg-slate-900/50 p-4">
        <Skeleton className="h-3 w-full rounded-full mb-2" />
        <div className="flex justify-between">
          <Skeleton className="h-4 w-20" />
          <Skeleton className="h-4 w-20" />
        </div>
      </div>
      <div className="grid grid-cols-4 gap-3">
        {[...Array(4)].map((_, i) => (
          <Skeleton key={i} className="h-24 rounded-lg" />
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <Skeleton className="h-10 flex-1 min-w-[250px]" />
        <Skeleton className="h-10 w-[150px]" />
      </div>
      <div className="space-y-3">
        {[...Array(3)].map((_, i) => (
          <Skeleton key={i} className="h-32 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}

export default function ComponentsPage() {
  const params = useParams();
  const projectId = params.id as string;

  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [selectedCapability, setSelectedCapability] = useState<TddCapability | null>(null);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [createModalOpen, setCreateModalOpen] = useState(false);

  // Fetch components and capabilities
  const { data: components = [], isLoading: componentsLoading, refetch: refetchComponents } = useQuery({
    queryKey: ["tdd-components", projectId],
    queryFn: () => fetchTddComponents(projectId),
  });

  const { data: capabilities = [], isLoading: capabilitiesLoading, refetch: refetchCapabilities } = useQuery({
    queryKey: ["tdd-capabilities", projectId],
    queryFn: () => fetchTddCapabilities(projectId),
  });

  const isLoading = componentsLoading || capabilitiesLoading;

  // Filter components and capabilities
  const filteredData = useMemo(() => {
    let filteredComponents = components;
    let filteredCapabilities = capabilities;

    // Status filter for capabilities
    if (statusFilter !== "all") {
      filteredCapabilities = capabilities.filter((c) => {
        if (statusFilter === "passing") return c.status === "tests_passing";
        if (statusFilter === "failing") return c.status === "failing";
        if (statusFilter === "pending") return c.status === "pending" || c.status === "not_implemented";
        return true;
      });
      // Only show components that have matching capabilities
      const componentIds = new Set(filteredCapabilities.map((c) => c.component_id));
      filteredComponents = components.filter((c) => componentIds.has(c.id));
    }

    // Search filter
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      filteredCapabilities = filteredCapabilities.filter(
        (c) =>
          c.capability_id.toLowerCase().includes(q) ||
          c.name.toLowerCase().includes(q)
      );
      // Show components that either match or have matching capabilities
      const componentIds = new Set(filteredCapabilities.map((c) => c.component_id));
      filteredComponents = components.filter(
        (c) =>
          componentIds.has(c.id) ||
          c.component_id.toLowerCase().includes(q) ||
          c.name.toLowerCase().includes(q)
      );
    }

    return { components: filteredComponents, capabilities: filteredCapabilities };
  }, [components, capabilities, statusFilter, searchQuery]);

  const handleSelectCapability = (capability: TddCapability) => {
    setSelectedCapability(capability);
    setDrawerOpen(true);
  };

  const handleLockCapability = async (capabilityId: string) => {
    try {
      await lockTddCapability(projectId, capabilityId);
      refetchCapabilities();
    } catch (err) {
      console.error("Failed to lock capability:", err);
    }
  };

  const handleRefresh = () => {
    refetchComponents();
    refetchCapabilities();
  };

  if (isLoading) {
    return (
      <div className="h-full overflow-auto p-4">
        <ComponentsPageSkeleton />
      </div>
    );
  }

  return (
    <div className="h-full overflow-auto p-4 space-y-4">
      {/* Build Progress */}
      <BuildProgress components={components} capabilities={capabilities} />

      {/* Filters and Actions */}
      <div className="flex flex-wrap gap-3">
        <div className="relative flex-1 min-w-[250px]">
          <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-500" />
          <Input
            type="text"
            placeholder="Search components or capabilities..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="pl-9"
          />
        </div>

        <Select value={statusFilter} onValueChange={setStatusFilter}>
          <SelectTrigger className="w-[140px]">
            <SelectValue placeholder="All Status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="passing">Passing</SelectItem>
            <SelectItem value="failing">Failing</SelectItem>
            <SelectItem value="pending">Pending</SelectItem>
            <SelectItem value="locked">Locked</SelectItem>
          </SelectContent>
        </Select>

        <Button variant="outline" onClick={handleRefresh}>
          <RefreshCw className="h-4 w-4 mr-1.5" />
          Refresh
        </Button>

        <Button onClick={() => setCreateModalOpen(true)}>
          <Plus className="h-4 w-4 mr-1.5" />
          Create Component
        </Button>
      </div>

      {/* Component Suggestions */}
      <ComponentSuggestions
        projectId={projectId}
        onComponentCreated={refetchComponents}
      />

      {/* Results count */}
      <div className="text-sm text-slate-500">
        {filteredData.components.length > 0
          ? `Showing ${filteredData.components.length} component${filteredData.components.length !== 1 ? "s" : ""} with ${filteredData.capabilities.length} capabilit${filteredData.capabilities.length !== 1 ? "ies" : "y"}`
          : components.length > 0
          ? "No results match your filters"
          : "No components found. Accept specs to create components."}
      </div>

      {/* Components List */}
      <ComponentList
        components={filteredData.components}
        capabilities={filteredData.capabilities}
        isLoading={false}
        onSelectCapability={handleSelectCapability}
        onLockCapability={handleLockCapability}
      />

      {/* Capability Drawer */}
      <CapabilityDrawer
        capability={selectedCapability}
        projectId={projectId}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
      />

      {/* Create Component Modal */}
      <CreateComponentModal
        projectId={projectId}
        open={createModalOpen}
        onOpenChange={setCreateModalOpen}
        onSuccess={refetchComponents}
      />
    </div>
  );
}
