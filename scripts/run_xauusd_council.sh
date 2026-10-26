#!/bin/bash
# Everything in one go on a Mac: set up Python, download real XAUUSD prices from Dukascopy, convene the
# council and open the transcript. Run it again any time: downloaded days are kept, so only new days
# are fetched.
#
#   bash scripts/run_xauusd_council.sh                    # 8 scripted bots, 3 rounds, data from 2020
#   bash scripts/run_xauusd_council.sh --brain claude     # Claude drives the bots (an estimated $1-2 a run)
#   START=2018-01-01 BOTS=12 bash scripts/run_xauusd_council.sh
# Any other options are passed on to `python -m xauusd_council run` (see xauusd_council/README.md).
set -euo pipefail
cd "$(dirname "$0")/.."

if [ ! -d .venv ]; then
    PYTHON=$(command -v python3.12 || command -v python3.13 || command -v python3.11 || true)
    if [ -z "$PYTHON" ] && python3 -c 'import sys; sys.exit(sys.version_info < (3, 11))' 2>/dev/null; then
        PYTHON=$(command -v python3)
    fi
    if [ -z "$PYTHON" ]; then
        echo "Python 3.11 or newer is needed: install it from https://www.python.org/downloads/ and run this again."
        exit 1
    fi
    echo "Setting up Python in .venv ..."
    "$PYTHON" -m venv .venv
fi
source .venv/bin/activate
echo "Installing requirements ..."
pip install --quiet -r requirements.txt

DATA=data/xauusd_m1.csv
if [ ! -f "$DATA" ] || [ "$(find "$DATA" -mtime +0 2>/dev/null)" ]; then
    echo "Downloading XAUUSD one-minute prices from ${START:-2020-01-01} (the first time takes a few minutes) ..."
    python -m xauusd_council fetch --start "${START:-2020-01-01}" --out "$DATA"
fi

OUT="data/council/real-$(date +%Y%m%d-%H%M%S)"
python -m xauusd_council run --data "$DATA" --bots "${BOTS:-8}" --rounds "${ROUNDS:-3}" --brain scripted \
    --out "$OUT" "$@"
open "$OUT/transcript.md" 2>/dev/null || echo "Transcript: $OUT/transcript.md"
