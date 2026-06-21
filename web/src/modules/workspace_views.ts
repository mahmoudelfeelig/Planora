export const WORKSPACE_VIEWS = [
  "schedule",
  "results",
  "review",
  "settings",
  "generator",
  "fairness",
  "history",
] as const;

export type WorkspaceView = typeof WORKSPACE_VIEWS[number];

export function switchWorkspaceView(
  view: string,
  options: { onChange?: (view: WorkspaceView) => void } = {},
): void {
  const selected = (WORKSPACE_VIEWS as readonly string[]).includes(view) ? view as WorkspaceView : "schedule";
  WORKSPACE_VIEWS.forEach((name) => {
    const panel = document.getElementById(`${name}-view`) || (name === "schedule" ? document.getElementById("schedule-shell") : null);
    const tab = document.getElementById(`view-${name}`);
    const active = name === selected;
    if (panel) {
      panel.hidden = !active;
      panel.classList.toggle("active", active);
    }
    if (tab) tab.classList.toggle("active", active);
  });
  options.onChange?.(selected);
}
