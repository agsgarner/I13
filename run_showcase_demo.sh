#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
source venv/bin/activate
export PATH="/Library/TeX/texbin:$PATH"

STAMP="$(date +%Y%m%d_%H%M%S)"
ROOT="artifacts/showcase_live/${STAMP}"
VENV_PY="venv/bin/python3"
export MPLCONFIGDIR="${TMPDIR:-/tmp}/i13-mplconfig"
mkdir -p "${ROOT}"
mkdir -p "${MPLCONFIGDIR}"

echo "=== I13 Senior Design Showcase Demo ==="
echo "Artifact root: ${ROOT}"
echo ""

echo "[1/5] Dependency check"
"${VENV_PY}" - <<'PY'
import importlib.util, shutil
checks = {
    "matplotlib": importlib.util.find_spec("matplotlib") is not None,
    "gradio_client_optional": importlib.util.find_spec("gradio_client") is not None,
    "lcapy_optional": importlib.util.find_spec("lcapy") is not None,
    "ngspice": shutil.which("ngspice") is not None,
}
for name, ok in checks.items():
    print(f"- {name}: {'found' if ok else 'missing'}")
PY
echo ""

echo "[2/5] Available demo cases"
"${VENV_PY}" main.py list-cases | sed -n '1,30p'
echo ""

echo "[3/5] Running live parameter sweeps"
"${VENV_PY}" demo_showcase.py --case rc_lowpass --sweep target_fc_hz=500,1000,5000 --output-dir "${ROOT}/rc_lowpass"
"${VENV_PY}" demo_showcase.py --case common_source --sweep target_gain_db=10,20,30 --output-dir "${ROOT}/common_source"
"${VENV_PY}" demo_showcase.py --case mos_buffer --sweep load_cap_f=1e-12,5e-12,20e-12 --output-dir "${ROOT}/mos_buffer"
"${VENV_PY}" demo_showcase.py --case current_mirror --sweep target_iout_a=50e-6,100e-6,200e-6 --output-dir "${ROOT}/current_mirror"
echo ""

echo "[4/5] Showcase comparison files"
find "${ROOT}" \( -name 'comparison_summary.md' -o -name 'comparison_table.csv' -o -name 'comparison_plot.png' \) -print | sort
echo ""

echo "[5/5] Key generated artifacts"
find artifacts/simulations -path '*generated.sp' -o -path '*schematic.png' -o -path '*ac_plot.svg' -o -path '*dc_plot.svg' -o -path '*tran_plot.svg' -o -path '*final_report.txt' | tail -80
echo ""
echo "Open these first:"
find "${ROOT}" -name 'comparison_summary.md' -print | sort
