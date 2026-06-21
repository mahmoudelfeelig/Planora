import type { Dict } from "../types";

export function ProjectsPanel({ projects, onRefresh }: { projects: Dict[]; onRefresh(): void }) {
  return (
    <section className="panel">
      <div className="panel-heading">
        <h2>Projects</h2>
        <button type="button" onClick={onRefresh}>Refresh</button>
      </div>
      <div className="table-like">
        <div className="table-row header"><span>Name</span><span>Tenant</span><span>Owner</span></div>
        {projects.length ? projects.map((project) => (
          <div className="table-row" key={`${project.tenant_id || "default"}-${project.name}`}>
            <span>{String(project.name)}</span>
            <span>{String(project.tenant_id || "default")}</span>
            <span>{String(project.created_by || "-")}</span>
          </div>
        )) : <div className="empty-row">No saved projects visible for this role.</div>}
      </div>
    </section>
  );
}
