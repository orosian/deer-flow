import { getBackendBaseURL } from "../config";
import { isStaticWebsiteOnly } from "../static-mode";

import type { GraphPresetsResponse } from "./types";

const STATIC_GRAPH_PRESETS_RESPONSE: GraphPresetsResponse = {
  presets: [],
};

export async function loadGraphPresets(): Promise<GraphPresetsResponse> {
  if (isStaticWebsiteOnly()) {
    return STATIC_GRAPH_PRESETS_RESPONSE;
  }

  const res = await fetch(`${getBackendBaseURL()}/api/graph-presets`);
  const data = (await res.json()) as Partial<GraphPresetsResponse>;
  return {
    presets: data.presets ?? [],
  };
}
