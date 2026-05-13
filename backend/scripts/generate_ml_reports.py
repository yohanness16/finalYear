"""Generate ML performance reports and plots."""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from app.db.session import AsyncSessionLocal
from app.services.ai_predictor import model_loaded, predict_eta_adjustment, reload_model
from app.services.ml_dataset import build_training_rows
from app.services.trainer import train_from_db


def _safe_div(numerator: float, denominator: float) -> float:
    return float(numerator) / float(denominator) if denominator else 0.0


def _mape(actual: np.ndarray, pred: np.ndarray) -> float:
    denom = np.where(actual == 0, 1.0, actual)
    return float(np.mean(np.abs((actual - pred) / denom)) * 100.0)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _plot_scatter(actual: np.ndarray, pred: np.ndarray, out_path: Path, title: str) -> None:
    plt.figure(figsize=(6, 6))
    plt.scatter(actual, pred, s=12, alpha=0.5)
    max_val = max(float(actual.max()), float(pred.max()), 1.0)
    plt.plot([0, max_val], [0, max_val], "r--", linewidth=1)
    plt.xlabel("Actual seconds")
    plt.ylabel("Predicted seconds")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


def _plot_error_hist(errors: np.ndarray, out_path: Path, title: str) -> None:
    plt.figure(figsize=(6, 4))
    plt.hist(errors, bins=30, color="#4C72B0", alpha=0.85)
    plt.xlabel("Error seconds")
    plt.ylabel("Count")
    plt.title(title)
    plt.tight_layout()
    plt.savefig(out_path)
    plt.close()


async def generate_reports(output_dir: Path, train_model: bool) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)

    async with AsyncSessionLocal() as db:
        if train_model:
            success, message = await train_from_db(db)
            report_path = output_dir / "train_summary.txt"
            report_path.write_text(message + "\n")
            reload_model()
            if not success:
                return 1

        rows = await build_training_rows(db)

    if not rows:
        (output_dir / "empty.txt").write_text("No training rows found.\n")
        return 1

    records = []
    for row in rows:
        features = row["features"]
        heuristic_eta = float(row["heuristic_eta"])
        actual = float(row["actual_segment"])
        adjustment = predict_eta_adjustment(features)
        ml_eta = heuristic_eta + float(adjustment or 0.0)
        records.append(
            {
                **features,
                "actual_segment": actual,
                "heuristic_eta": heuristic_eta,
                "ml_eta": ml_eta,
                "ml_residual": float(adjustment or 0.0),
            }
        )

    df = pd.DataFrame(records)
    df.to_csv(output_dir / "training_rows.csv", index=False)

    actual = df["actual_segment"].to_numpy(dtype=float)
    heuristic = df["heuristic_eta"].to_numpy(dtype=float)
    ml_eta = df["ml_eta"].to_numpy(dtype=float)

    metrics = {
        "count": int(len(df)),
        "heuristic_mae": float(np.mean(np.abs(actual - heuristic))),
        "heuristic_rmse": float(np.sqrt(np.mean((actual - heuristic) ** 2))),
        "heuristic_mape": _mape(actual, heuristic),
        "ml_mae": float(np.mean(np.abs(actual - ml_eta))),
        "ml_rmse": float(np.sqrt(np.mean((actual - ml_eta) ** 2))),
        "ml_mape": _mape(actual, ml_eta),
    }
    _write_json(output_dir / "metrics.json", metrics)

    pd.DataFrame([metrics]).to_csv(output_dir / "metrics.csv", index=False)

    _plot_scatter(actual, heuristic, output_dir / "scatter_heuristic.png", "Actual vs Heuristic")
    _plot_scatter(actual, ml_eta, output_dir / "scatter_ml.png", "Actual vs ML")
    _plot_error_hist(actual - heuristic, output_dir / "error_hist_heuristic.png", "Heuristic Errors")
    _plot_error_hist(actual - ml_eta, output_dir / "error_hist_ml.png", "ML Errors")

    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate ML performance reports")
    parser.add_argument("--output", default="ml_reports", help="Output directory")
    parser.add_argument("--train", action="store_true", help="Train model before reporting")
    args = parser.parse_args()

    output_dir = Path(args.output)
    return asyncio.run(generate_reports(output_dir, args.train))


if __name__ == "__main__":
    raise SystemExit(main())
