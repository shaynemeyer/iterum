#!/usr/bin/env bash
# Install the iterum command and the Claude Code plugin from this checkout,
# then record this machine's audit as the first events in the ledger.
# Usage: ./install.sh, or ITERUM_DEVICE=laptop ./install.sh to skip the prompt.
set -euo pipefail

cd "$(dirname "$0")"
here=$(pwd)

need() {
  command -v "$1" >/dev/null || { echo "install.sh: $1 not found. $2" >&2; exit 1; }
}
need git "Install git first."
need uv "Install uv first: https://docs.astral.sh/uv/getting-started/installation/"

if [ -z "${ITERUM_DEVICE:-}" ]; then
  if [ ! -t 0 ]; then
    echo "install.sh: set ITERUM_DEVICE, e.g. ITERUM_DEVICE=laptop ./install.sh" >&2
    exit 1
  fi
  default=$(hostname -s)
  read -r -p "Name for this machine [$default]: " ITERUM_DEVICE
  ITERUM_DEVICE=${ITERUM_DEVICE:-$default}
fi
export ITERUM_DEVICE

echo "== installing the iterum command"
uv tool install --editable .
iterum="$(uv tool dir --bin)/iterum"

echo "== auditing this machine"
"$iterum" doctor
uv run scripts/seed-ledger.py

echo "== building knowledge"
"$iterum" project >/dev/null || true   # an empty knowledge table reports DRIFT once
"$iterum" project

if command -v claude >/dev/null; then
  echo "== installing the Claude Code plugin"
  claude plugin marketplace add "$here"
  claude plugin install iterum@iterum
else
  echo "== skipped the plugin: claude not found. Install Claude Code, then run:"
  echo "   claude plugin marketplace add \"$here\" && claude plugin install iterum@iterum"
fi

echo
echo "Done. Add to your shell profile (~/.zshrc or ~/.bashrc), then open a new terminal:"
echo "  export ITERUM_DEVICE=$ITERUM_DEVICE"
if [ "$here" != "$HOME/github/iterum" ]; then
  echo "  export ITERUM_HOME=\"$here\""
fi
command -v iterum >/dev/null || echo "iterum is not on your PATH yet: run uv tool update-shell"
