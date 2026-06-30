import { useState } from "react";
import type { Dict } from "../types";

type Props = {
  projects: Dict[];
  canWrite: boolean;
  canSave: boolean;
  onRefresh(): void;
  onSave(name: string): Promise<void>;
  onOpen(project: Dict): Promise<void>;
  onDelete(project: Dict): Promise<void>;
  onRename(project: Dict, nextName: string): Promise<void>;
};

export function ProjectsPanel({ projects, canWrite, canSave, onRefresh, onSave, onOpen, onDelete, onRename }: Props) {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);

  const run = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="panel">
      <div className="panel-heading">
        <div><h2>Projects</h2><p className="section-copy">Save the current workspace or reopen a tenant-scoped timetable snapshot.</p></div>
        <button type="button" disabled={busy} onClick={onRefresh}>Refresh</button>
      </div>
      {canWrite ? (
        <div className="identity-grid access-controls">
          <label>Project name<input value={name} onChange={(event) => setName(event.target.value)} placeholder="Fall 2026 working schedule" /></label>
          <button type="button" disabled={busy || !canSave || !name.trim()} onClick={() => void run(async () => {
            await onSave(name.trim());
            setName("");
          })}>Save current workspace</button>
        </div>
      ) : null}
      {projects.length ? (
        <div className="table-like">
          <div className="table-row header"><span>Name</span><span>Tenant</span><span>Owner / Actions</span></div>
          {projects.map((project) => (
          <div className="table-row" key={`${project.tenant_id || "default"}-${project.name}`}>
            <span>{String(project.name)}</span>
            <span>{String(project.tenant_id || "default")}</span>
            <span className="table-actions">
              <small>{String(project.created_by || "legacy")}</small>
              <button type="button" disabled={busy} onClick={() => void run(() => onOpen(project))}>Open</button>
              {canWrite && project.storage !== "legacy" ? (
                <>
                  <button type="button" className="secondary-button" disabled={busy} onClick={() => {
                    const nextName = window.prompt("New project name", String(project.name));
                    if (nextName?.trim() && nextName.trim() !== String(project.name)) void run(() => onRename(project, nextName.trim()));
                  }}>Rename</button>
                  <button type="button" className="danger-button" disabled={busy} onClick={() => {
                    if (window.confirm(`Delete project ${String(project.name)}?`)) void run(() => onDelete(project));
                  }}>Delete</button>
                </>
              ) : null}
            </span>
          </div>
          ))}
        </div>
      ) : (
        <div className="empty-state projects-empty">
          <strong>No saved projects</strong>
          <span>Load a scenario in Solver, then save the workspace here when it is ready to revisit.</span>
        </div>
      )}
    </section>
  );
}
