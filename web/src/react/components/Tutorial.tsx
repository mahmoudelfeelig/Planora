import { useEffect, useRef, useState } from "react";
import type { TutorialStep } from "../planner_api";

type Props = {
  open: boolean;
  steps: TutorialStep[];
  onClose(): void;
  onOpenData(): void;
  onOpenSchedule(): void;
};

export function Tutorial({ open, steps, onClose, onOpenData, onOpenSchedule }: Props) {
  const [active, setActive] = useState(0);
  const closeRef = useRef<HTMLButtonElement>(null);
  const dialogRef = useRef<HTMLElement>(null);
  const returnFocusRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    if (!open) return;
    returnFocusRef.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    setActive(0);
    window.setTimeout(() => closeRef.current?.focus(), 0);
    return () => returnFocusRef.current?.focus();
  }, [open]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
      if (event.key === "Tab") {
        const focusable = [...(dialogRef.current?.querySelectorAll<HTMLElement>(
          'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
        ) ?? [])].filter((element) => element.offsetParent !== null);
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open || !steps.length) return null;
  const step = steps[Math.min(active, steps.length - 1)];
  const last = active === steps.length - 1;

  const finish = () => {
    onClose();
    onOpenData();
  };

  return (
    <div className="tutorial-backdrop" role="presentation" onMouseDown={(event) => event.target === event.currentTarget && onClose()}>
      <section ref={dialogRef} className="tutorial-dialog" role="dialog" aria-modal="true" aria-labelledby="tutorial-title">
        <header className="tutorial-header">
          <div className="tutorial-brand">
            <img src="/app-icon.png" alt="" />
            <div>
              <span>Planora guide</span>
              <strong id="tutorial-title">Your timetable, from data to publish</strong>
            </div>
          </div>
          <button ref={closeRef} type="button" className="quiet-button" onClick={onClose}>Close</button>
        </header>

        <div className="tutorial-layout">
          <nav className="tutorial-steps" aria-label="Tutorial steps">
            {steps.map((item, index) => (
              <button
                key={item.id}
                type="button"
                className={index === active ? "active" : index < active ? "complete" : ""}
                onClick={() => setActive(index)}
                aria-current={index === active ? "step" : undefined}
              >
                <span>Step {index + 1}</span>
                <strong>{item.title}</strong>
              </button>
            ))}
          </nav>

          <div className="tutorial-content" aria-live="polite">
            <span className="eyebrow">Step {active + 1} of {steps.length}</span>
            <h2>{step.title}</h2>
            <p>{step.description}</p>
            <div className="tutorial-example">
              {active === 0 ? <><strong>Start with what you have</strong><span>Use the Spring 2023 example, or bring your own CSV.</span></> : null}
              {active === 1 ? <><strong>Warnings are review prompts</strong><span>Planora keeps required rules separate from preferences so you know what must be fixed.</span></> : null}
              {active === 2 ? <><strong>Choose an outcome, not an algorithm</strong><span>Balanced is a strong everyday default. Technical settings stay in Advanced.</span></> : null}
              {active === 3 ? <><strong>Every suggestion includes a reason</strong><span>Select a class to see conflicts and safe alternatives in the inspector.</span></> : null}
              {active === 4 ? <><strong>Publish only when the checks are clear</strong><span>Validate the draft, resolve hard conflicts, then export or publish.</span></> : null}
            </div>
          </div>
        </div>

        <footer className="tutorial-actions">
          <button type="button" className="secondary-button" disabled={active === 0} onClick={() => setActive((value) => Math.max(0, value - 1))}>Back</button>
          <div>
            <button type="button" className="quiet-button" onClick={() => { onClose(); onOpenSchedule(); }}>Skip to schedule</button>
            {last
              ? <button type="button" onClick={finish}>Choose timetable data</button>
              : <button type="button" onClick={() => setActive((value) => Math.min(steps.length - 1, value + 1))}>Continue</button>}
          </div>
        </footer>
      </section>
    </div>
  );
}
