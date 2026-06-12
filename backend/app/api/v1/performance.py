"""Performance benchmark results API.

Provides endpoints to:
  - Download results as CSV (GET)
  - View results as JSON (GET)
  - Get a summary report (GET)
  - Get a formatted text report (GET)

All endpoints require admin authentication.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException
from fastapi.responses import PlainTextResponse

from app.core.security import RequireAdmin

router = APIRouter(tags=["performance"])

RESULTS_DIR = Path(__file__).resolve().parents[3] / "storage"
CSV_PATH = RESULTS_DIR / "benchmark_results.csv"
JSON_PATH = RESULTS_DIR / "benchmark_results.json"


@router.get("/admin/performance/csv")
async def download_csv(current_user: RequireAdmin):
    """
    Download benchmark results as a CSV file.
    Returns the raw CSV with Content-Disposition header for download.
    Admin only.
    """
    if not CSV_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="No benchmark results found. Run the performance tests first:\n"
                   "  python -m pytest tests/test_performance.py -v",
        )

    content = CSV_PATH.read_text()

    return PlainTextResponse(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": 'attachment; filename="benchmark_results.csv"',
        },
    )


@router.get("/admin/performance/json")
async def get_results_json(current_user: RequireAdmin):
    """Return benchmark results as JSON. Admin only."""
    if not JSON_PATH.exists():
        # Try to build from CSV
        if CSV_PATH.exists():
            rows: list[dict[str, Any]] = []
            with open(CSV_PATH, newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    rows.append(row)
            return {"results": rows, "count": len(rows)}
        raise HTTPException(
            status_code=404,
            detail="No benchmark results found. Run the performance tests first.",
        )

    data = json.loads(JSON_PATH.read_text())
    return {"results": data, "count": len(data)}


@router.get("/admin/performance/summary")
async def get_summary(current_user: RequireAdmin):
    """
    Return a human-readable summary of benchmark results.
    Groups by category and shows mean values. Admin only.
    """
    if not CSV_PATH.exists():
        raise HTTPException(
            status_code=404,
            detail="No benchmark results found.",
        )

    rows: list[dict[str, Any]] = []
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in rows:
            rows.append(row)

    if not rows:
        return {"message": "CSV file is empty."}

    # Group by category, show only _mean metrics
    summary: dict[str, dict[str, str]] = {}
    for row in rows:
        if not row.get("metric", "").endswith("_mean"):
            continue
        cat = row.get("category", "unknown")
        metric = row["metric"].replace("_mean", "")
        value = row.get("value", "N/A")
        unit = row.get("unit", "")
        if cat not in summary:
            summary[cat] = {}
        summary[cat][metric] = f"{value} {unit}"

    # Also collect metadata
    api_base = rows[-1].get("api_base", "unknown") if rows else "unknown"
    timestamp = rows[-1].get("timestamp", "unknown") if rows else "unknown"

    return {
        "api_base": api_base,
        "last_run": timestamp,
        "total_rows": len(rows),
        "categories": list(summary.keys()),
        "summary": summary,
    }


@router.get("/admin/performance/report")
async def get_report(current_user: RequireAdmin):
    """
    Return a formatted text report suitable for inclusion in thesis. Admin only.
    """
    if not CSV_PATH.exists():
        raise HTTPException(status_code=404, detail="No benchmark results found.")

    rows: list[dict[str, Any]] = []
    with open(CSV_PATH, newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(row)

    if not rows:
        return PlainTextResponse("No data available.", media_type="text/plain")

    # Build report
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("BusTrack Performance Benchmark Report")
    lines.append("=" * 70)
    lines.append(f"API Base: {rows[-1].get('api_base', 'unknown')}")
    lines.append(f"Last Run: {rows[-1].get('timestamp', 'unknown')}")
    lines.append(f"Total Measurements: {len(rows)}")
    lines.append("")

    # Group by category
    categories: dict[str, list[dict]] = {}
    for row in rows:
        cat = row.get("category", "unknown")
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(row)

    for cat, cat_rows in categories.items():
        lines.append(f"--- {cat.upper().replace('_', ' ')} ---")
        lines.append("")

        # Show mean, p95, stddev for each metric
        metrics: dict[str, dict[str, str]] = {}
        for row in cat_rows:
            metric = row.get("metric", "")
            value = row.get("value", "")
            unit = row.get("unit", "")
            base = metric.replace("_mean", "").replace("_median", "").replace("_p95", "").replace("_min", "").replace("_max", "").replace("_stddev", "")
            if base not in metrics:
                metrics[base] = {}
            metrics[base][metric] = f"{value} {unit}"

        for base, vals in metrics.items():
            mean_val = vals.get(f"{base}_mean", "N/A")
            p95_val = vals.get(f"{base}_p95", "")
            std_val = vals.get(f"{base}_stddev", "")
            min_val = vals.get(f"{base}_min", "")
            max_val = vals.get(f"{base}_max", "")

            line = f"  {base}: mean={mean_val}"
            if p95_val:
                line += f", p95={p95_val}"
            if std_val:
                line += f", stddev={std_val}"
            if min_val and max_val:
                line += f", range=[{min_val}, {max_val}]"
            lines.append(line)

        lines.append("")

    lines.append("=" * 70)
    lines.append("End of Report")
    lines.append("=" * 70)

    return PlainTextResponse("\n".join(lines), media_type="text/plain")
