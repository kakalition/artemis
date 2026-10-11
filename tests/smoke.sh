#!/usr/bin/env bash
# Artemis end-to-end smoke test. Runs entirely against a throwaway ARTEMIS_HOME.
set -euo pipefail

cd "$(dirname "$0")/.."

export ARTEMIS_HOME="$(mktemp -d)"
export MODEL_NAME="${MODEL_NAME:-openai:gpt-4o-mini}"
trap 'rm -rf "$ARTEMIS_HOME"' EXIT

echo "== version =="
uv run artemis version

echo "== import =="
uv run artemis import tests/fixtures/sample.csv

echo "== re-import (dedupe) =="
uv run artemis import tests/fixtures/sample.csv

echo "== report =="
uv run artemis report --period 2026-01

echo "== budget set + status =="
uv run artemis budget --set Groceries --amount 50 --period 2026-01
uv run artemis budget --period 2026-01

echo "== portfolio =="
uv run artemis portfolio --add AAPL --quantity 2 --cost 300
uv run artemis portfolio --price AAPL --value 160
uv run artemis portfolio

echo "== mcp server (in-process) =="
uv run python tests/mcp_smoke.py

if [ "${ARTEMIS_SMOKE_RENDER:-0}" = "1" ]; then
  echo "== render chart + pdf =="
  uv run artemis report --period 2026-01 --chart --pdf
fi

echo "SMOKE OK"
