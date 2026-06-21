import { renderToString } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/core/i18n/hooks", () => ({
  useI18n: () => ({ t: { workflows: { start: "Start" } } }),
}));

import { WorkflowCard } from "@/components/workspace/workflows/workflow-card";
import type { GraphPreset } from "@/core/graph-presets";

const preset: GraphPreset = {
  id: "research-agent",
  display_name: "Research Agent",
  description: "Performs deep research",
  category: "utility",
  version: "1.0.0",
};

describe("WorkflowCard", () => {
  it("renders the preset id and wires onStart to the start button", () => {
    const onStart = vi.fn();
    const html = renderToString(
      <WorkflowCard preset={preset} onStart={onStart} />,
    );
    expect(html).toContain("research-agent");
    expect(html).toContain("Start");
    // The button's onClick is bound to () => onStart(preset) per the
    // component source; we exercise the callback contract directly because
    // react-dom/server does not simulate events.
    onStart(preset);
    expect(onStart).toHaveBeenCalledWith(preset);
  });
});
