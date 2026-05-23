#!/usr/bin/env bash
# Python venv + requirements.
set -euo pipefail

echo "==> [5/6] python env"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENV="$REPO_DIR/.venv"

if [[ ! -d "$VENV" ]]; then
    # --system-site-packages so the venv can see the system-installed
    # `hailo_platform` python module (from python3-hailort) which is not
    # available on PyPI.
    python3 -m venv --system-site-packages "$VENV"
fi

# shellcheck disable=SC1091
source "$VENV/bin/activate"

pip install --upgrade pip wheel
pip install -r "$REPO_DIR/requirements.txt"

# sanity-check that hailo bindings are visible
python3 -c "import hailo_platform; print('    hailo_platform:', hailo_platform.__version__ if hasattr(hailo_platform, '__version__') else 'ok')" \
    || { echo "    ⚠ hailo_platform not importable inside venv — was python3-hailort installed?"; exit 1; }

echo "    venv ready at $VENV"
