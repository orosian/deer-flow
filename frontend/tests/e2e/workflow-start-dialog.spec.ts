import { expect, test } from "@playwright/test";

import { mockLangGraphAPI } from "./utils/mock-api";

const PRESET_WITH_INPUTS = {
  id: "research-agent",
  display_name: "Research Agent",
  description: "Performs deep research",
  category: "utility",
  version: "1.0.0",
  input_ports: [
    { key: "topic", type: "string", required: true, description: "Topic" },
    { key: "depth", type: "enum", enum_values: ["shallow", "deep"], required: true },
    { key: "include_citations", type: "boolean", required: false },
    { key: "notes", type: "multiline", required: false },
  ],
};

const PRESET_WITHOUT_INPUTS = {
  id: "quick-summary",
  display_name: "Quick Summary",
  description: "One-shot summarization with no inputs",
  category: "utility",
  version: "1.0.0",
};

async function mockGraphPresets(page: import("@playwright/test").Page, presets: unknown[]) {
  await page.route("**/api/graph-presets", (route) => {
    if (route.request().method() === "GET") {
      return route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ presets }),
      });
    }
    return route.fallback();
  });
}

test.describe("WorkflowStartDialog", () => {
  test("opens dialog with controls when a preset has input_ports and Confirm navigates with URL params", async ({
    page,
  }) => {
    mockLangGraphAPI(page);
    await mockGraphPresets(page, [PRESET_WITH_INPUTS]);

    await page.goto("/workspace/workflows");
    await expect(page.getByText("Research Agent")).toBeVisible({ timeout: 15_000 });

    // Click the card's Start button — opens the dialog
    await page.getByRole("button", { name: /^Start$/ }).first().click();

    // Dialog title + dynamic description appear
    await expect(page.getByRole("heading", { name: "Start workflow" })).toBeVisible();
    await expect(page.getByText(/Configure inputs for Research Agent/)).toBeVisible();

    // String + enum controls are present
    const topicInput = page.locator("#wf-port-research-agent-topic");
    await expect(topicInput).toBeVisible();

    // Required field is empty → Confirm is disabled
    const confirm = page.getByRole("button", { name: /^Start$/ }).last();
    await expect(confirm).toBeDisabled();

    // Fill the required string input
    await topicInput.fill("LangGraph");

    // Confirm should now be enabled
    await expect(confirm).toBeEnabled();

    // Cancel path first — verify the dialog closes and URL does not change
    await page.getByRole("button", { name: /^Cancel$/ }).click();
    await expect(page.getByRole("heading", { name: "Start workflow" })).toBeHidden();
    expect(page.url()).toContain("/workspace/workflows");

    // Re-open and confirm — verify URL contains expected query params
    await page.getByRole("button", { name: /^Start$/ }).first().click();
    await page.locator("#wf-port-research-agent-topic").fill("LangGraph");
    await page.getByRole("button", { name: /^Start$/ }).last().click();

    await page.waitForURL(/\/workspace\/chats\//, { timeout: 10_000 });
    const url = new URL(page.url());
    expect(url.pathname.startsWith("/workspace/chats/")).toBe(true);
    expect(url.searchParams.get("preset")).toBe("research-agent");
    expect(url.searchParams.get("input.topic")).toBe("LangGraph");
  });

  test("navigates directly to chat when preset has no input_ports", async ({ page }) => {
    mockLangGraphAPI(page);
    await mockGraphPresets(page, [PRESET_WITHOUT_INPUTS]);

    await page.goto("/workspace/workflows");
    await expect(page.getByText("Quick Summary")).toBeVisible({ timeout: 15_000 });

    await page.getByRole("button", { name: /^Start$/ }).first().click();

    // Direct navigation — no dialog in between
    await page.waitForURL(/\/workspace\/chats\//, { timeout: 10_000 });
    const url = new URL(page.url());
    expect(url.pathname.startsWith("/workspace/chats/")).toBe(true);
    expect(url.searchParams.get("preset")).toBe("quick-summary");
    // No input.<key> params should be present
    for (const key of url.searchParams.keys()) {
      expect(key.startsWith("input.")).toBe(false);
    }
  });
});