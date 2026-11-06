"""Normalize extracted public CT DPH capacity snapshots and run a baseline audit."""
from __future__ import annotations

import csv
import json
import re
import statistics
from collections import Counter
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HIST = ROOT / "data" / "reservoirs" / "historical"
SNAPSHOT = ROOT / "data" / "reservoirs" / "2024-11-12.json"
ROW = re.compile(
    r"^(CT\d{7})\s+(.+?)\s+(\d{1,2}/\d{1,2}/\d{4})\s+(\d+(?:\.\d+)?)\s+"
    r"(.+?)\s+(↑↑|↑|↓↓|↓|--)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+"
    r"(\d{1,2}/\d{1,2}/\d{4})\s+(\d+(?:\.\d+)?)\s+([A-Z ]+)$"
)
FIELDS = [
    "report_date", "source_url", "pwsid", "system_name", "reading_date", "percent_full",
    "status", "trend_symbol", "historical_average_percent_full", "percent_of_normal",
    "previous_date", "previous_percent_full", "county_served",
]


def as_iso(value: str) -> str:
    return datetime.strptime(value, "%m/%d/%Y").date().isoformat()


def main() -> None:
    manifest = json.loads((HIST / "manifest.json").read_text(encoding="utf-8"))
    rows: list[dict] = []
    failures = []
    for report in manifest:
        report_rows = []
        for line in (ROOT / report["text"]).read_text(encoding="utf-8").splitlines():
            match = ROW.match(line.strip())
            if not match:
                continue
            g = match.groups()
            report_rows.append({
                "report_date": report["report_date"], "source_url": report["url"],
                "pwsid": g[0], "system_name": g[1], "reading_date": as_iso(g[2]),
                "percent_full": float(g[3]), "status": g[4], "trend_symbol": g[5],
                "historical_average_percent_full": float(g[6]), "percent_of_normal": int(g[7]),
                "previous_date": as_iso(g[8]), "previous_percent_full": float(g[9]),
                "county_served": g[10].strip(),
            })
        if len(report_rows) != 34:
            failures.append({"report_date": report["report_date"], "parsed_rows": len(report_rows)})
        rows.extend(report_rows)

    latest = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    latest_url = latest["source"]["url"]
    for r in latest["systems"]:
        rows.append({
            "report_date": latest["report_date"], "source_url": latest_url,
            "pwsid": r["pwsid"], "system_name": r["name"], "reading_date": r["reading_date"],
            "percent_full": r["percent_full"], "status": r["status"], "trend_symbol": r["trend"],
            "historical_average_percent_full": r["historical_average_percent_full"],
            "percent_of_normal": r["percent_of_normal"], "previous_date": r["previous_date"],
            "previous_percent_full": r["previous_percent_full"], "county_served": r["county_served"],
        })

    rows.sort(key=lambda x: (x["report_date"], x["pwsid"]))
    out_csv = HIST / "public-system-readings.csv"
    with out_csv.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    systems_by_report = {r["report_date"]: {x["pwsid"] for x in rows if x["report_date"] == r["report_date"]} for r in rows}
    report_dates = sorted(systems_by_report)
    all_systems = sorted(set().union(*systems_by_report.values()))
    report_pairs = []
    eval_rows = []
    by_date_system = {(r["report_date"], r["pwsid"]): r for r in rows}
    for a_date, b_date in zip(report_dates, report_dates[1:]):
        a_day, b_day = date.fromisoformat(a_date), date.fromisoformat(b_date)
        pair_result = {"issue_report_date": a_date, "next_report_date": b_date, "matched_systems": 0, "eligible_targets": 0}
        for pwsid in sorted(systems_by_report[a_date] & systems_by_report[b_date]):
            a = by_date_system[(a_date, pwsid)]
            b = by_date_system[(b_date, pwsid)]
            target_day = date.fromisoformat(b["reading_date"])
            horizon = (target_day - a_day).days
            input_day = date.fromisoformat(a["reading_date"])
            input_age = (a_day - input_day).days
            if not (7 <= horizon <= 21) or not (0 <= input_age <= 14):
                continue
            # Both predictors use only measurements already published by issue date.
            observed = float(b["percent_full"])
            persistence_forecast = float(a["percent_full"])
            error = persistence_forecast - observed
            previous_day = date.fromisoformat(a["previous_date"])
            interval_days = (input_day - previous_day).days
            trend_forecast = persistence_forecast
            if interval_days > 0:
                daily_change = (persistence_forecast - float(a["previous_percent_full"])) / interval_days
                trend_forecast = max(0.0, min(100.0, persistence_forecast + daily_change * (target_day - input_day).days))
            trend_error = trend_forecast - observed
            eval_rows.append({
                "issue_report_date": a_date, "target_report_date": b_date, "pwsid": pwsid,
                "issue_reading_date": a["reading_date"], "target_reading_date": b["reading_date"],
                "input_age_days": input_age, "horizon_days": horizon,
                "persistence_forecast_percent_full": round(persistence_forecast, 4),
                "trend_extrapolation_forecast_percent_full": round(trend_forecast, 4),
                "observed_percent_full": observed, "error_forecast_minus_observed": round(error, 4),
                "absolute_error": round(abs(error), 4),
                "trend_error_forecast_minus_observed": round(trend_error, 4),
                "trend_absolute_error": round(abs(trend_error), 4),
            })
            pair_result["matched_systems"] += 1
            pair_result["eligible_targets"] += 1
        report_pairs.append(pair_result)

    eval_fields = ["issue_report_date", "target_report_date", "pwsid", "issue_reading_date", "target_reading_date", "input_age_days", "horizon_days", "persistence_forecast_percent_full", "trend_extrapolation_forecast_percent_full", "observed_percent_full", "error_forecast_minus_observed", "absolute_error", "trend_error_forecast_minus_observed", "trend_absolute_error"]
    with (HIST / "persistence-holdout.csv").open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=eval_fields)
        writer.writeheader()
        writer.writerows(eval_rows)

    metrics = {
        "method": "Last published current percent-full reading carried forward unchanged (persistence baseline).",
        "issue_policy": "At each dated report, use only its current and previous reading. Score against the next dated report only when the target measurement is 7-21 days after the issue report date and the issue reading is no more than 14 days old.",
        "selection": "No model fitting or tuning. Compare persistence with a pre-specified linear continuation of the last two reported values, bounded to 0-100%. This is a chronological, near-two-week baseline diagnostic; report dates are sparse and snapshots are not independent.",
        "reports": len(report_dates), "report_dates": report_dates,
        "systems_seen": len(all_systems), "system_ids": all_systems,
        "rows": len(rows), "rows_per_system": dict(sorted(Counter(r["pwsid"] for r in rows).items())),
        "row_parse_failures": failures,
        "evaluation_targets": len(eval_rows),
        "evaluation_report_pairs": report_pairs,
        "mean_absolute_error_percent_points": round(statistics.mean(x["absolute_error"] for x in eval_rows), 3) if eval_rows else None,
        "mean_error_forecast_minus_observed_percent_points": round(statistics.mean(x["error_forecast_minus_observed"] for x in eval_rows), 3) if eval_rows else None,
        "median_absolute_error_percent_points": round(statistics.median(x["absolute_error"] for x in eval_rows), 3) if eval_rows else None,
        "trend_mean_absolute_error_percent_points": round(statistics.mean(x["trend_absolute_error"] for x in eval_rows), 3) if eval_rows else None,
        "trend_mean_error_forecast_minus_observed_percent_points": round(statistics.mean(x["trend_error_forecast_minus_observed"] for x in eval_rows), 3) if eval_rows else None,
        "trend_median_absolute_error_percent_points": round(statistics.median(x["trend_absolute_error"] for x in eval_rows), 3) if eval_rows else None,
        "caution": "Rows from the same system and time period are correlated; this diagnostic does not establish independent validation, does not compare seasonal or weather-driven models, and does not support reservoir-specific or farm-specific inferences.",
    }
    (HIST / "history-audit.json").write_text(json.dumps(metrics, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: metrics[k] for k in ["reports", "report_dates", "systems_seen", "rows", "row_parse_failures", "evaluation_targets", "mean_absolute_error_percent_points", "mean_error_forecast_minus_observed_percent_points", "median_absolute_error_percent_points", "trend_mean_absolute_error_percent_points", "trend_mean_error_forecast_minus_observed_percent_points", "trend_median_absolute_error_percent_points"]}, indent=2))


if __name__ == "__main__":
    main()
