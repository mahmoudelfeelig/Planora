import type { ApiClient } from "./api";
import type { SolverSettings } from "./solver_settings";
import type { Dict, Instance } from "./types";

export type UiScenario = {
  id: "demo" | "spring_2023" | "import" | string;
  label: string;
  description: string;
  endpoint_mode?: string;
  badge?: string;
};

export type UiRunMode = {
  id: "fast" | "balanced" | "quality" | string;
  label: string;
  description: string;
  recommended?: boolean;
};

export type TutorialStep = {
  id: string;
  title: string;
  description: string;
  action_label?: string;
};

export type UiContract = {
  version: string;
  scenarios: UiScenario[];
  modes: UiRunMode[];
  tutorial: TutorialStep[];
};

export const DEFAULT_UI_CONTRACT: UiContract = {
  version: "planora.ui.v1",
  scenarios: [
    {
      id: "demo",
      label: "Demo timetable",
      description: "A small example for learning the workflow in a few moments.",
      endpoint_mode: "demo",
      badge: "Quick start",
    },
    {
      id: "spring_2023",
      label: "Spring 2023 university",
      description: "A university-scale planning scenario calibrated from the Spring 2023 data.",
      endpoint_mode: "spring_2023",
      badge: "University scale",
    },
    {
      id: "import",
      label: "Import your data",
      description: "Bring an existing timetable or institutional CSV into a new workspace.",
      badge: "Your institution",
    },
  ],
  modes: [
    { id: "fast", label: "Fast", description: "Create a valid draft with the shortest wait." },
    {
      id: "balanced",
      label: "Balanced",
      description: "A practical balance of speed and timetable quality.",
      recommended: true,
    },
    { id: "quality", label: "Maximum quality", description: "Spend more time reducing gaps and disruption." },
  ],
  tutorial: [
    { id: "bring-data", title: "Bring in your timetable", description: "Open the Spring 2023 example or import your university data." },
    { id: "check-essentials", title: "Check the essentials", description: "Confirm the term, rooms, people, groups, and the rules that must never be broken." },
    { id: "build-draft", title: "Build a draft", description: "Choose Fast, Balanced, or Maximum quality. Planora handles the technical settings." },
    { id: "review-repair", title: "Review and repair", description: "Open a flagged class, read the reason, and apply an explained suggestion." },
    { id: "validate-publish", title: "Validate and publish", description: "Confirm there are no hard conflicts, then publish or export the timetable." },
  ],
};

function arrayOfObjects(value: unknown): Dict[] {
  return Array.isArray(value)
    ? value.filter((entry): entry is Dict => Boolean(entry) && typeof entry === "object" && !Array.isArray(entry))
    : [];
}

function normalizeNamedRows(value: unknown, defaults: UiScenario[] | UiRunMode[]): Dict[] {
  if (!Array.isArray(value)) return [];
  return value.flatMap((entry) => {
    if (entry && typeof entry === "object" && !Array.isArray(entry)) return [entry as Dict];
    if (typeof entry !== "string") return [];
    const fallback = defaults.find((row) => row.id === entry);
    return [{ id: entry, label: fallback?.label || entry, description: fallback?.description || "" }];
  });
}

export function normalizeUiContract(payload: Dict): UiContract {
  const nested = payload.ui_contract && typeof payload.ui_contract === "object"
    ? payload.ui_contract as Dict
    : payload;
  const version = String(nested.version || nested.contract_version || "");
  if (version !== "planora.ui.v1") {
    throw new Error(
      `Incompatible Planora UI contract: ${version || "missing"}. Expected planora.ui.v1.`,
    );
  }

  const scenarios = normalizeNamedRows(nested.scenarios, DEFAULT_UI_CONTRACT.scenarios).map((row) => ({
    id: String(row.id || ""),
    label: String(row.label || row.id || "Scenario"),
    description: String(row.description || ""),
    endpoint_mode: row.endpoint_mode ? String(row.endpoint_mode) : undefined,
    badge: row.badge ? String(row.badge) : undefined,
  })).filter((row) => row.id);
  const modes = normalizeNamedRows(
    nested.run_modes ?? nested.modes,
    DEFAULT_UI_CONTRACT.modes,
  ).map((row) => ({
    id: String(row.id || ""),
    label: String(row.label || row.id || "Mode"),
    description: String(row.description || row.body || ""),
    recommended: Boolean(row.recommended),
  })).filter((row) => row.id);
  const tutorialSource = nested.tutorial_steps ?? nested.tutorial;
  const tutorial = arrayOfObjects(tutorialSource).map((row, index) => ({
    id: String(row.id || `step-${index + 1}`),
    title: String(row.title || `Step ${index + 1}`),
    description: String(row.description || row.body || ""),
    action_label: row.action_label ? String(row.action_label) : undefined,
  }));

  if (!scenarios.length || !modes.length || !tutorial.length) {
    throw new Error("The Planora backend UI contract is incomplete.");
  }

  return {
    version,
    scenarios,
    modes,
    tutorial,
  };
}

export async function loadUiContract(client: ApiClient): Promise<UiContract> {
  return normalizeUiContract(await client.get<Dict>("/capabilities"));
}

export class PlannerApi {
  constructor(private readonly client: ApiClient) {}

  async loadScenario(scenario: UiScenario, institutionPolicy = "", demandMode = ""): Promise<{ instance: Instance }> {
    const endpointMode = scenario.endpoint_mode || scenario.id;
    const query = new URLSearchParams();
    if (institutionPolicy) query.set("institution_policy", institutionPolicy);
    if (demandMode) query.set("demand_mode", demandMode);
    const suffix = query.size ? `?${query.toString()}` : "";
    return this.client.get<{ instance: Instance }>(`/preset/${encodeURIComponent(endpointMode)}${suffix}`);
  }

  solve(
    sessionId: string,
    mode: string,
    advanced: SolverSettings,
    useAdvancedOverrides = false,
  ): Promise<Dict> {
    const payload: Dict = { run_mode: mode };
    if (useAdvancedOverrides) {
      payload.advanced_overrides = {
        solve: {
          room_mode: advanced.roomMode,
          objective_profile: advanced.profile,
          time_limit_seconds: advanced.timeLimitSeconds,
          workers: advanced.workers,
          use_objective: advanced.useObjective,
        },
      };
      payload.hard_constraints = {
        force_repeat_weekly_pattern: advanced.forceRepeatWeeklyPattern,
      };
    }
    return this.client.post<Dict>(`/sessions/${sessionId}/solve`, payload);
  }

  improve(
    sessionId: string,
    mode: string,
    advanced: SolverSettings,
    useAdvancedOverrides = false,
  ): Promise<Dict> {
    const payload: Dict = { run_mode: mode };
    if (useAdvancedOverrides) {
      payload.advanced_overrides = {
        improve: {
          iterations: advanced.improveIterations,
          max_seconds: advanced.improveSeconds,
          progress_every: advanced.progressEvery,
        },
      };
    }
    return this.client.post<Dict>(`/sessions/${sessionId}/improve`, payload);
  }

  validate(sessionId: string): Promise<Dict> {
    return this.client.post<Dict>(`/sessions/${sessionId}/score`, {});
  }
}
