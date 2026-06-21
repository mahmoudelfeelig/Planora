import type { Dict } from "../types";

export function ParityPanel({ manifest }: { manifest: Dict }) {
  const items = Array.isArray(manifest.items) ? manifest.items as Dict[] : [];
  return (
    <section className="panel">
      <h2>Desktop / Backend / Web Parity</h2>
      <p className="muted">
        Coverage {String(manifest.coverage_percent ?? 0)}% ({String(manifest.covered ?? 0)}/{String(manifest.total ?? 0)})
      </p>
      <div className="table-like">
        <div className="table-row header"><span>Capability</span><span>Status</span><span>Surfaces</span></div>
        {items.map((item) => (
          <div className="table-row" key={String(item.capability)}>
            <span>{String(item.capability)}</span>
            <span>{String(item.status)}</span>
            <span>D:{String(item.desktop)} B:{String(item.backend)} W:{String(item.web)}</span>
          </div>
        ))}
      </div>
    </section>
  );
}
