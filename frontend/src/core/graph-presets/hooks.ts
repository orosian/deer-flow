import { useQuery } from "@tanstack/react-query";

import { loadGraphPresets } from "./api";

export function useGraphPresets({
  enabled = true,
}: { enabled?: boolean } = {}) {
  const { data, isLoading, error } = useQuery({
    queryKey: ["graph-presets"],
    queryFn: () => loadGraphPresets(),
    enabled,
    refetchOnWindowFocus: false,
  });
  return {
    presets: data?.presets ?? [],
    isLoading,
    error,
  };
}
