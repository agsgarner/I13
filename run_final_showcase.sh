#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
source venv/bin/activate
export PATH="/Library/TeX/texbin:$PATH"

MODE="${1:-safe}"
PORT="${DEMO_UI_PORT:-8501}"
VENV_PY="venv/bin/python3"

export MPLCONFIGDIR="${TMPDIR:-/tmp}/i13-mplconfig"
export I13_SCHEMATIC_LCAPY_TIMEOUT="${I13_SCHEMATIC_LCAPY_TIMEOUT:-3}"
mkdir -p "${MPLCONFIGDIR}"

which python3
python3 -c "import streamlit, gradio_client, lcapy; print('ENV OK')"

print_paths() {
  echo ""
  echo "OPEN THIS:"
  echo "artifacts/showcase_runs/latest/summary.md"
  echo "artifacts/showcase_runs/latest/index.html"
  if [[ "${1:-}" == "ui" ]]; then
    echo ""
    echo "OPEN UI:"
    echo "http://localhost:${PORT}"
  fi
  echo ""
  echo "KEY FOLDERS:"
  echo "artifacts/showcase_runs/latest/netlists/"
  echo "artifacts/showcase_runs/latest/schematics/"
  echo "artifacts/showcase_runs/latest/plots/"
  echo "artifacts/showcase_runs/latest/reports/"
}

case "${MODE}" in
  safe)
    export USE_HF_NETLIST=0
    export USE_OPENAI=0
    export LLM_BACKEND=rule_based
    export I13_SHOWCASE_COMMAND="bash run_final_showcase.sh safe"
    "${VENV_PY}" tools/final_showcase_runner.py
    print_paths
    ;;
  full)
    export USE_HF_NETLIST=0
    export USE_OPENAI=0
    export LLM_BACKEND=rule_based
    export I13_SHOWCASE_COMMAND="bash run_final_showcase.sh full"
    "${VENV_PY}" tools/final_showcase_runner.py --cases rc,rlc_bandpass,mirror,common_source,folded_cascode_opamp
    print_paths
    echo ""
    echo "OPEN LIVE UI:"
    echo "streamlit run ui_showcase.py"
    echo ""
    echo "OPEN STATIC SHOWCASE:"
    echo "artifacts/showcase_runs/latest/index.html"
    echo ""
    echo "SAFE DEMO COMMAND:"
    echo "bash run_final_showcase.sh safe"
    echo ""
    echo "OPTIONAL HF DEMO:"
    echo "bash run_final_showcase.sh hf"
    ;;
  hf)
    export HF_SPACE_ID="${HF_SPACE_ID:-potatoman869/spice_netlist-generator}"
    export USE_HF_NETLIST=1
    export I13_SHOWCASE_COMMAND="bash run_final_showcase.sh hf"
    "${VENV_PY}" tools/test_hf_netlist_backend.py
    "${VENV_PY}" tools/final_showcase_runner.py --cases rc --skip-preflight
    print_paths
    ;;
  ui)
    print_paths ui
    if "${VENV_PY}" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('streamlit') else 1)"; then
      I13_STREAMLIT_APP=1 streamlit run ui_showcase.py --server.address 127.0.0.1 --server.port "${PORT}"
    else
      "${VENV_PY}" ui_showcase.py --port "${PORT}"
    fi
    ;;
  *)
    echo "Usage: bash run_final_showcase.sh {safe|full|hf|ui}"
    exit 2
    ;;
esac
