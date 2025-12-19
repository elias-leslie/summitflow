"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchFeatures, updateFeatureStatus, type Feature, type FeatureStatus, type FeaturesListResponse } from "@/lib/api";

// ============================================================================
// Query Keys
// ============================================================================

export const featureKeys = {
  all: ["features"] as const,
  list: (projectId: string) => [...featureKeys.all, "list", projectId] as const,
  detail: (projectId: string, featureId: string) => [...featureKeys.all, "detail", projectId, featureId] as const,
};

// ============================================================================
// useFeatures Hook
// ============================================================================

interface UseFeaturesOptions {
  category?: string;
  health_status?: string;
  limit?: number;
  offset?: number;
}

export function useFeatures(projectId: string, options: UseFeaturesOptions = {}) {
  return useQuery<FeaturesListResponse>({
    queryKey: featureKeys.list(projectId),
    queryFn: () => fetchFeatures(projectId, options),
    enabled: !!projectId,
    staleTime: 1000 * 60, // 1 minute
  });
}

// ============================================================================
// useUpdateFeatureStatus Hook with Optimistic Updates
// ============================================================================

interface UpdateStatusVariables {
  featureId: string;
  newStatus: FeatureStatus;
}

export function useUpdateFeatureStatus(projectId: string) {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ featureId, newStatus }: UpdateStatusVariables) =>
      updateFeatureStatus(projectId, featureId, newStatus),

    // Optimistic update
    onMutate: async ({ featureId, newStatus }) => {
      // Cancel any outgoing refetches
      await queryClient.cancelQueries({ queryKey: featureKeys.list(projectId) });

      // Snapshot the previous value
      const previousData = queryClient.getQueryData<FeaturesListResponse>(featureKeys.list(projectId));

      // Optimistically update to the new value
      queryClient.setQueryData<FeaturesListResponse>(featureKeys.list(projectId), (old) => {
        if (!old) return old;

        return {
          ...old,
          features: old.features.map((feature) =>
            feature.feature_id === featureId
              ? { ...feature, status: newStatus }
              : feature
          ),
        };
      });

      // Return context with the previous data
      return { previousData };
    },

    // If mutation fails, roll back to the previous value
    onError: (_err, _variables, context) => {
      if (context?.previousData) {
        queryClient.setQueryData(featureKeys.list(projectId), context.previousData);
      }
    },

    // Always refetch after error or success
    onSettled: () => {
      queryClient.invalidateQueries({ queryKey: featureKeys.list(projectId) });
    },
  });
}
