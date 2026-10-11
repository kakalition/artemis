#!/usr/bin/env bash
# Idempotent setup for Artemis.
set -euo pipefail

cd "$(dirname "$0")"

echo "== syncing dependencies (uv) =="
# includes the local Phoenix observability UI (on by default)
uv sync --extra dev --extra observability-phoenix

if [ ! -f .env ]; then
  echo "== creating .env from .env.example =="
  cp .env.example .env
  echo "Edit .env and set OPENAI_API_KEY before running 'artemis chat'."
fi

echo "== done =="
echo "Try: uv run artemis version && uv run artemis report --period this-month"
