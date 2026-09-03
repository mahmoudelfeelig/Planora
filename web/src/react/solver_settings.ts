export type SolverSettings = {
  roomMode: string;
  profile: string;
  timeLimitSeconds: number;
  workers: number;
  useObjective: boolean;
  forceRepeatWeeklyPattern: boolean;
  improveIterations: number;
  improveSeconds: number;
  progressEvery: number;
};

export type PlanningOutcome = "speed" | "balanced" | "quality" | "research" | "verification";

export const DEFAULT_SETTINGS: SolverSettings = {
  roomMode: "partitioned",
  profile: "university_fast",
  timeLimitSeconds: 15,
  workers: 4,
  useObjective: false,
  forceRepeatWeeklyPattern: false,
  improveIterations: 500,
  improveSeconds: 2,
  progressEvery: 10,
};

export function settingsForOutcome(
  outcome: PlanningOutcome,
  current: SolverSettings,
  forceRepeatWeeklyPattern: boolean,
): SolverSettings {
  const recommended: Record<PlanningOutcome, Partial<SolverSettings>> = {
    speed: {
      roomMode: "partitioned",
      profile: "university_fast",
      timeLimitSeconds: 15,
      useObjective: false,
      improveIterations: 0,
      improveSeconds: 1,
    },
    balanced: {
      roomMode: "greedy",
      profile: "balanced",
      timeLimitSeconds: 30,
      useObjective: true,
      improveIterations: 1500,
      improveSeconds: 5,
    },
    quality: {
      roomMode: "cp_rooms",
      profile: "quality_first",
      timeLimitSeconds: 300,
      useObjective: true,
      improveIterations: 5000,
      improveSeconds: 60,
    },
    research: {
      roomMode: "partitioned",
      profile: "research_adaptive",
      timeLimitSeconds: 180,
      useObjective: false,
      improveIterations: 0,
      improveSeconds: 1,
    },
    verification: {
      roomMode: "cp_rooms",
      profile: "verification",
      timeLimitSeconds: 300,
      useObjective: true,
      improveIterations: 0,
      improveSeconds: 1,
    },
  };
  return {
    ...current,
    ...recommended[outcome],
    forceRepeatWeeklyPattern,
  };
}
