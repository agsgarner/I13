#!/usr/bin/env python3
import argparse
import os
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "i13-mplconfig"))
os.environ.setdefault("I13_SCHEMATIC_LCAPY_TIMEOUT", "3")

from core.showcase_artifacts import (  # noqa: E402
    LATEST_ROOT,
    organize_showcase_latest,
    row_from_final_state,
    sweep_group_from_output,
)
from demo_showcase import run_sweep  # noqa: E402
from main import run_case, run_preflight  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Run the final offline-safe showcase and build artifacts/showcase_runs/latest")
    parser.add_argument("--skip-preflight", action="store_true")
    parser.add_argument(
        "--cases",
        default="rc,rlc_bandpass,mirror,common_source,folded_cascode_opamp",
        help="Comma-separated safe standalone cases",
    )
    args = parser.parse_args()

    command = os.getenv("I13_SHOWCASE_COMMAND", "bash run_final_showcase.sh")
    if not args.skip_preflight:
        run_preflight("ti_safe")

    case_rows = []
    for case_name in [item.strip() for item in args.cases.split(",") if item.strip()]:
        print(f"[final-showcase] Running safe case: {case_name}")
        final_state = run_case(case_name)
        case_rows.append(row_from_final_state(case_name, final_state))

    sweep_root = Path("artifacts/showcase_runs/_latest_working/rc_lowpass_target_fc")
    rows, output_dir = run_sweep(
        "rc_lowpass",
        "target_fc_hz",
        [500.0, 1000.0, 5000.0],
        output_dir=str(sweep_root),
        update_latest=False,
    )
    sweep_groups = [
        sweep_group_from_output(
            "rc_lowpass_target_fc_hz",
            str(output_dir),
            rows,
        )
    ]

    organize_showcase_latest(
        command=command,
        case_rows=case_rows,
        sweep_groups=sweep_groups,
        architecture_summary=(
            "TopologyAgent uses cookbook motifs, device-selection heuristics, and templates to choose reusable analog structures. "
            "SizingAgent applies design-equation and template defaults for first-pass component values. "
            "NetlistAgent routes netlist synthesis through optional Hugging Face/OpenAI backends with deterministic templates as the offline-safe fallback. "
            "ConstraintAgent and OperatingPointAgent use equation and heuristic references for sanity checks, SimulationAgent runs ngspice and extracts metrics, "
            "and RefinementAgent uses bounded equation-driven updates when measured results miss targets."
        ),
        clean=True,
    )

    print("")
    print("OPEN THIS FOR THE SHOWCASE:")
    print(LATEST_ROOT / "summary.md")
    print("")
    print("KEY FOLDERS:")
    for name in ("netlists", "schematics", "plots", "reports"):
        print(LATEST_ROOT / name)


if __name__ == "__main__":
    main()
