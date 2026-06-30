import type { Dict } from "../types";

export function ParityPanel({ manifest }: { manifest: Dict }) {
  const items = Array.isArray(manifest.items) ? manifest.items as Dict[] : [];
  return (
    <section className="panel">
      <div className="panel-heading">
        <div>
          <h2>Platform coverage</h2>
          <p className="section-copy">Track which scheduling capabilities are available across the desktop app, backend API, and web workspace.</p>
        </div>
        <span className="coverage-badge">
          {String(manifest.coverage_percent ?? 0)}% · {String(manifest.covered ?? 0)}/{String(manifest.total ?? 0)}
        </span>
      </div>
      <div className="table-like parity-table">
        <div className="table-row header"><span>Capability</span><span>Status</span><span>Surfaces</span></div>
        {items.map((item) => (
          <div className="table-row" key={String(item.capability)}>
            <span className="parity-capability">{String(item.capability)}</span>
            <span data-label="Status">{String(item.status)}</span>
            <span data-label="Surfaces">D:{String(item.desktop)} B:{String(item.backend)} W:{String(item.web)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
