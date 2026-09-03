import { useEffect, useMemo, useState } from "react";
import type { Dict } from "../types";
import {
  settingsForOutcome,
  type PlanningOutcome,
  type SolverSettings,
} from "../solver_settings";

export type InstitutionPolicy = {
  id: string;
  label: string;
  objective_profile: string;
  evidence_status: string;
  demand_policy: Dict;
  hard_constraints: Dict;
  institutional_policy: Dict;
};

export type WizardConfiguration = {
  scenario: string;
  institutionPolicy: string;
  demandMode: "nominal" | "forecast" | "conservative";
  outcome: PlanningOutcome;
  settings: SolverSettings;
};

type Props = {
  presets: string[];
  policies: InstitutionPolicy[];
  settings: SolverSettings;
  busy: boolean;
  onApply(configuration: WizardConfiguration): Promise<void>;
};

const OUTCOMES: Array<{ id: PlanningOutcome; label: string; description: string }> = [
  { id: "speed", label: "Publish quickly", description: "Prioritize a validated feasible timetable and low waiting time." },
  { id: "balanced", label: "Balanced operations", description: "Spend a moderate budget improving gaps, active days, and consistency." },
  { id: "quality", label: "Best practical quality", description: "Use a longer exact and local improvement budget for day-to-day operations." },
  { id: "research", label: "Proof-guided research", description: "Use reusable exact neighborhoods, adaptive search, bounds, and a machine-readable trace." },
  { id: "verification", label: "Audit and certify", description: "Favor the joint CP room model and expose objective bounds and optimality gaps." },
];

const DEMAND_OPTIONS = [
  { id: "nominal" as const, label: "Current enrollment", description: "Size rooms from the current student counts." },
  { id: "forecast" as const, label: "Likely demand", description: "Use the 90th-percentile forecast when scenarios are available." },
  { id: "conservative" as const, label: "Demand buffer", description: "Protect against multiple simultaneous enrollment increases." },
];

const HARD_CONSTRAINT_LABELS: Record<string, string> = {
  enforce_room_capacity: "Room capacity",
  enforce_room_availability: "Room availability",
  enforce_calendar_rules: "Calendar rules",
  enforce_building_closures: "Building closures",
  enforce_travel_time_buffers: "Travel buffers",
  enforce_standard_start_slots: "Standard start times",
};

function readable(value: string): string {
  return value.replaceAll("_", " ").replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function enabledConstraintLabels(policy: InstitutionPolicy | undefined): string[] {
  if (!policy) return [];
  return Object.entries(policy.hard_constraints)
    .filter(([, enabled]) => enabled === true)
    .map(([key]) => HARD_CONSTRAINT_LABELS[key] || readable(key));
}

function missingEvidence(policy: InstitutionPolicy | undefined): string[] {
  const raw = policy?.institutional_policy.known_missing_evidence;
  return Array.isArray(raw) ? raw.filter((value): value is string => typeof value === "string") : [];
}

export function AdminSetupWizard({ presets, policies, settings, busy, onApply }: Props) {
  const [step, setStep] = useState(0);
  const [scenario, setScenario] = useState(presets.includes("giu_target") ? "giu_target" : (presets[0] || ""));
  const [institutionPolicy, setInstitutionPolicy] = useState(
    policies.some((policy) => policy.id === "giu_target") ? "giu_target" : (policies[0]?.id || ""),
  );
  const [outcome, setOutcome] = useState<PlanningOutcome>("balanced");
  const [demandMode, setDemandMode] = useState<WizardConfiguration["demandMode"]>("forecast");
  const [repeatPattern, setRepeatPattern] = useState(false);
  const selectedPolicy = useMemo(
    () => policies.find((policy) => policy.id === institutionPolicy),
    [institutionPolicy, policies],
  );
  const recommendedSettings = useMemo(
    () => settingsForOutcome(outcome, settings, repeatPattern),
    [outcome, repeatPattern, settings],
  );
  const enabledConstraints = useMemo(() => enabledConstraintLabels(selectedPolicy), [selectedPolicy]);
  const evidenceGaps = useMemo(() => missingEvidence(selectedPolicy), [selectedPolicy]);
  const steps = ["Scenario", "Institution", "Priorities", "Uncertainty", "Review"];

  useEffect(() => {
    if (!scenario && presets.length) {
      setScenario(presets.includes("giu_target") ? "giu_target" : presets[0]);
    }
  }, [presets, scenario]);

  useEffect(() => {
    if (!institutionPolicy && policies.length) {
      setInstitutionPolicy(
        policies.some((policy) => policy.id === "giu_target") ? "giu_target" : policies[0].id,
      );
    }
  }, [institutionPolicy, policies]);

  const canContinue = step === 0 ? Boolean(scenario) : step === 1 ? Boolean(institutionPolicy) : true;
  const apply = async () => {
    await onApply({
      scenario,
      institutionPolicy,
      demandMode,
      outcome,
      settings: recommendedSettings,
    });
  };

  return (
    <section className="setup-wizard" aria-labelledby="setup-wizard-title">
      <div className="setup-wizard-heading">
        <div>
          <span className="eyebrow">Guided setup</span>
          <h3 id="setup-wizard-title">Configure a scheduling run without solver jargon</h3>
          <p>Answer four operational questions. Planora will choose the policy, uncertainty model, and solver profile; advanced settings remain editable.</p>
        </div>
        <span className="wizard-step-count">{step + 1} of {steps.length}</span>
      </div>

      <ol className="wizard-progress" aria-label="Setup progress">
        {steps.map((label, index) => (
          <li key={label} className={index === step ? "active" : index < step ? "complete" : ""} aria-current={index === step ? "step" : undefined}>
            <button type="button" disabled={busy || index > step} onClick={() => setStep(index)}>
              <span>{index + 1}</span>{label}
            </button>
          </li>
        ))}
      </ol>

      <div className="wizard-body">
        {step === 0 ? (
          <fieldset>
            <legend>What are you scheduling?</legend>
            <p className="wizard-help">Start from a representative dataset. You can still import institutional data afterward.</p>
            <label>
              Scenario
              <select value={scenario} onChange={(event) => setScenario(event.target.value)}>
                <option value="">Choose a scenario</option>
                {presets.map((preset) => <option key={preset} value={preset}>{readable(preset)}</option>)}
              </select>
            </label>
          </fieldset>
        ) : null}

        {step === 1 ? (
          <fieldset>
            <legend>Which institution policy should apply?</legend>
            <p className="wizard-help">A preset can supply room, calendar, travel, standard-start, demand, and utilization assumptions. Its evidence label tells you what still needs local confirmation.</p>
            <div className="wizard-choice-grid">
              {policies.map((policy) => (
                <label className={`wizard-choice ${institutionPolicy === policy.id ? "selected" : ""}`} key={policy.id}>
                  <input type="radio" name="institution-policy" value={policy.id} checked={institutionPolicy === policy.id} onChange={() => setInstitutionPolicy(policy.id)} />
                  <strong>{policy.label}</strong>
                  <span>{policy.evidence_status}</span>
                  {missingEvidence(policy).length ? <small>{missingEvidence(policy).length} local evidence checks remain</small> : null}
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}

        {step === 2 ? (
          <fieldset>
            <legend>What matters most for this run?</legend>
            <div className="wizard-choice-grid outcome-grid">
              {OUTCOMES.map((option) => (
                <label className={`wizard-choice ${outcome === option.id ? "selected" : ""}`} key={option.id}>
                  <input type="radio" name="planning-outcome" value={option.id} checked={outcome === option.id} onChange={() => setOutcome(option.id)} />
                  <strong>{option.label}</strong>
                  <span>{option.description}</span>
                </label>
              ))}
            </div>
          </fieldset>
        ) : null}

        {step === 3 ? (
          <fieldset>
            <legend>How should uncertainty and repetition be handled?</legend>
            <div className="wizard-choice-grid">
              {DEMAND_OPTIONS.map((option) => (
                <label className={`wizard-choice ${demandMode === option.id ? "selected" : ""}`} key={option.id}>
                  <input type="radio" name="demand-mode" value={option.id} checked={demandMode === option.id} onChange={() => setDemandMode(option.id)} />
                  <strong>{option.label}</strong>
                  <span>{option.description}</span>
                </label>
              ))}
            </div>
            <label className="wizard-toggle">
              <input type="checkbox" checked={repeatPattern} onChange={(event) => setRepeatPattern(event.target.checked)} />
              <span><strong>Repeat the same weekly pattern</strong><small>Enable only when recurring activities really should keep the same time and room.</small></span>
            </label>
          </fieldset>
        ) : null}

        {step === 4 ? (
          <div className="wizard-review" aria-live="polite">
            <div><span>Scenario</span><strong>{readable(scenario)}</strong></div>
            <div><span>Institution</span><strong>{selectedPolicy?.label || readable(institutionPolicy)}</strong></div>
            <div><span>Goal</span><strong>{OUTCOMES.find((option) => option.id === outcome)?.label}</strong></div>
            <div><span>Demand protection</span><strong>{DEMAND_OPTIONS.find((option) => option.id === demandMode)?.label}</strong></div>
            <div><span>Recommended engine</span><strong>{readable(recommendedSettings.profile)}</strong></div>
            <div><span>Budget</span><strong>{recommendedSettings.timeLimitSeconds} seconds, {recommendedSettings.workers} workers</strong></div>
            <p className="wizard-evidence"><strong>Evidence boundary:</strong> {selectedPolicy?.evidence_status || "This policy must be calibrated locally before production use."}</p>
            <section className="wizard-review-wide" aria-labelledby="wizard-hard-checks-title">
              <span id="wizard-hard-checks-title">Hard checks enabled</span>
              <div className="wizard-policy-chips">
                {enabledConstraints.length ? enabledConstraints.map((label) => <strong key={label}>{label}</strong>) : <em>No preset hard checks</em>}
              </div>
            </section>
            {evidenceGaps.length ? (
              <section className="wizard-review-wide wizard-evidence-gaps" aria-labelledby="wizard-evidence-gaps-title">
                <span id="wizard-evidence-gaps-title">Confirm before institutional use</span>
                <ul>{evidenceGaps.map((gap) => <li key={gap}>{gap}</li>)}</ul>
              </section>
            ) : null}
          </div>
        ) : null}
      </div>

      <div className="wizard-actions">
        <button type="button" className="secondary-button" disabled={busy || step === 0} onClick={() => setStep((current) => Math.max(0, current - 1))}>Back</button>
        {step < steps.length - 1 ? (
          <button type="button" disabled={busy || !canContinue} onClick={() => setStep((current) => Math.min(steps.length - 1, current + 1))}>Continue</button>
        ) : (
          <button type="button" disabled={busy || !scenario || !institutionPolicy} onClick={() => void apply()}>Apply setup and load scenario</button>
        )}
      </div>
    </section>
  );
}
