#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT/simulation"
python 00_check.py
python -c "from api_client import APIClient; from gps_utils import haversine_m; print('simulation imports ok')"
