export const WORKSPACE_VIEWS = [
  "schedule",
  "results",
  "review",
  "settings",
  "generator",
  "fairness",
  "history",
];

export function switchWorkspaceView(view, options = {}) {
  const selected = WORKSPACE_VIEWS.includes(view) ? view : "schedule";
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
  if (options.onChange) options.onChange(selected);
}
