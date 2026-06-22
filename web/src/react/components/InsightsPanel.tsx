import { useMemo } from "react";
import type { Dict, Instance, Schedule } from "../types";

type LoadRow = { id: string; name: string; total: number; weeks: number; peak: number };

function entityName(collection: Dict<Dict>, id: string, fallback: string): string {
  const row = collection[id] || collection[String(Number(id))] || {};
  return String(row.name || row.code || `${fallback} ${id}`);
}

function summarize(loads: Map<string, Map<number, number>>, names: Dict<Dict>, fallback: string): LoadRow[] {
  return Array.from(loads.entries()).map(([id, weekly]) => {
    const values = Array.from(weekly.values());
    return {
      id,
      name: entityName(names, id, fallback),
      total: values.reduce((sum, value) => sum + value, 0),
      weeks: weekly.size,
      peak: values.length ? Math.max(...values) : 0,
    };
  }).sort((a, b) => b.total - a.total || a.name.localeCompare(b.name));
}

function fairnessSpread(rows: LoadRow[]): string {
  if (!rows.length) return "n/a";
  const totals = rows.map((row) => row.total);
  return String(Math.max(...totals) - Math.min(...totals));
}

export function InsightsPanel({ instance, schedule }: { instance: Instance | null; schedule: Schedule }) {
  const insights = useMemo(() => {
    const staffLoads = new Map<string, Map<number, number>>();
    const groupLoads = new Map<string, Map<number, number>>();
    const roomUses = new Map<string, number>();
    if (!instance) return { staff: [], groups: [], roomUses, placements: 0 };

    Object.entries(schedule).forEach(([activityId, placement]) => {
      const activity = instance.activities[activityId] || instance.activities[String(Number(activityId))] || {};
      const week = Number(placement.week || 1);
      const staffId = String(placement.staff_id ?? activity.staff_id ?? "");
      const groupIds = Array.isArray(activity.group_ids)
        ? activity.group_ids.map(String)
        : [String(activity.group_id ?? placement.group_id ?? "")].filter(Boolean);
      if (staffId) {
        const weekly = staffLoads.get(staffId) || new Map<number, number>();
        weekly.set(week, (weekly.get(week) || 0) + 1);
        staffLoads.set(staffId, weekly);
      }
      groupIds.forEach((groupId) => {
        const weekly = groupLoads.get(groupId) || new Map<number, number>();
        weekly.set(week, (weekly.get(week) || 0) + 1);
        groupLoads.set(groupId, weekly);
      });
      const roomId = String(placement.room_id ?? "");
      if (roomId) roomUses.set(roomId, (roomUses.get(roomId) || 0) + 1);
    });
    return {
      staff: summarize(staffLoads, instance.staff, "Staff"),
      groups: summarize(groupLoads, instance.groups, "Group"),
      roomUses,
      placements: Object.keys(schedule).length,
    };
  }, [instance, schedule]);

  if (!instance || !insights.placements) {
    return <section className="panel"><h2>Insights</h2><p className="section-copy">Load or solve a timetable to compare teaching load, student load, and room utilization.</p></section>;
  }

  const usedRooms = insights.roomUses.size;
  const totalRooms = Object.keys(instance.rooms || {}).length;
  return (
    <section className="panel">
      <div className="panel-heading"><div><h2>Fairness and utilization</h2><p className="section-copy">Workload totals and weekly peaks expose imbalances that a single global penalty can hide.</p></div></div>
      <div className="metric-grid">
        <div><span>Scheduled activities</span><strong>{insights.placements}</strong></div>
        <div><span>Staff load spread</span><strong>{fairnessSpread(insights.staff)}</strong></div>
        <div><span>Group load spread</span><strong>{fairnessSpread(insights.groups)}</strong></div>
        <div><span>Rooms used</span><strong>{usedRooms} / {totalRooms}</strong></div>
      </div>
      <div className="split-grid">
        <div className="subpanel"><h3>Staff workload</h3><div className="table-like compact"><div className="table-row header"><span>Staff</span><span>Total</span><span>Peak week</span></div>{insights.staff.slice(0, 20).map((row) => <div className="table-row" key={row.id}><span>{row.name}</span><span>{row.total}</span><span>{row.peak}</span></div>)}</div></div>
        <div className="subpanel"><h3>Student-group workload</h3><div className="table-like compact"><div className="table-row header"><span>Group</span><span>Total</span><span>Peak week</span></div>{insights.groups.slice(0, 20).map((row) => <div className="table-row" key={row.id}><span>{row.name}</span><span>{row.total}</span><span>{row.peak}</span></div>)}</div></div>
      </div>
    </section>
  );
}
