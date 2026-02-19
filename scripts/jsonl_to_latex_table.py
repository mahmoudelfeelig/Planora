from __future__ import annotations

import argparse
import json
from statistics import median
from pathlib import Path


def fmt(v) -> str:
    if v is None:
        return "-"
    if isinstance(v, float):
        return f"{v:.2f}"
    return str(v)


def _escape_latex(value: object) -> str:
    return str(value).replace("_", "\\_")


def _is_feasible(row: dict) -> bool:
    if "feasible" in row:
        return bool(row.get("feasible"))
    return int(row.get("status", -1)) in (2, 4)


def _cp_seconds(row: dict) -> float | None:
    if row.get("cp_seconds_total") is not None:
        return float(row["cp_seconds_total"])
    if row.get("cp_seconds") is not None:
        return float(row["cp_seconds"])
    return None


def _penalty_median(values: list[float]) -> str:
    if not values:
        return "-"
    return fmt(float(median(values)))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--in", dest="inp", required=True, help="Input JSONL results file")
    ap.add_argument("--out", dest="outp", required=True, help="Output .tex file (table rows)")
    ap.add_argument("--aggregate", action="store_true", help="Aggregate rows by (scenario, requested room mode)")
    args = ap.parse_args()

    inp = Path(args.inp)
    outp = Path(args.outp)
    rows: list[dict] = []
    for line in inp.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))

    lines: list[str] = []
    if args.aggregate:
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in rows:
            key = (str(row.get("mode", "?")), str(row.get("requested_room_mode", row.get("room_mode", "?"))))
            grouped.setdefault(key, []).append(row)

        for (scenario, requested_mode) in sorted(grouped.keys()):
            group = grouped[(scenario, requested_mode)]
            runs = len(group)
            feasible_rows = [r for r in group if _is_feasible(r)]
            feasible_pct = (100.0 * len(feasible_rows) / runs) if runs else 0.0
            cp_times = [v for v in (_cp_seconds(r) for r in group) if v is not None]
            penalties_base = [float(r["penalty_base"]) for r in feasible_rows if r.get("penalty_base") is not None]
            penalties_ls = [float(r["penalty_ls"]) for r in feasible_rows if r.get("penalty_ls") is not None]
            retry_count = 0
            for r in group:
                attempts = r.get("attempts", [])
                if isinstance(attempts, list) and len(attempts) >= 2:
                    first = attempts[0] if isinstance(attempts[0], dict) else {}
                    for attempt in attempts[1:]:
                        if not isinstance(attempt, dict):
                            continue
                        if (
                            attempt.get("room_mode") == first.get("room_mode")
                            and bool(first.get("use_objective", False))
                            and not bool(attempt.get("use_objective", True))
                        ):
                            retry_count += 1
                            break

            lines.append(
                f"{_escape_latex(scenario)} & {_escape_latex(requested_mode)} & {runs} & {fmt(feasible_pct)}"
                f" & {fmt(float(median(cp_times)) if cp_times else None)}"
                f" & {_penalty_median(penalties_base)} & {_penalty_median(penalties_ls)} & {retry_count} \\\\"
            )
    else:
        for row in rows:
            scenario = _escape_latex(row.get("mode", "?"))
            nacts = (row.get("instance") or {}).get("activities", "?")
            requested_mode = _escape_latex(row.get("requested_room_mode", row.get("room_mode", "?")))
            final_mode = _escape_latex(row.get("final_room_mode", row.get("room_mode", "?")))
            cp_sec = _cp_seconds(row)
            status_name = _escape_latex(row.get("status_name", row.get("status", "?")))
            pen0 = row.get("penalty_base", None)
            pen1 = row.get("penalty_ls", None)
            lines.append(
                f"{scenario} & {nacts} & {requested_mode} & {final_mode} & {fmt(cp_sec)} & {status_name} & {fmt(pen0)} & {fmt(pen1)} \\\\"
            )

    outp.parent.mkdir(parents=True, exist_ok=True)
    outp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
