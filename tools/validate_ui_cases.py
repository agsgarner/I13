#!/usr/bin/env python3
"""Validate the recommended live-demo prompts end-to-end.

Runs the same backend functions the UI uses, checks that:
- the prompt parser maps to the expected case
- run_case completes
- artifacts (generated.sp, schematic, plot, final_report) exist
- simulation_results expose the expected metrics
- the normalized metrics_display dict is populated

Prints a summary table and exits non-zero if any required piece is missing.
"""
import os
import sys
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("I13_SCHEMATIC_LCAPY_TIMEOUT", "3")

from ui_showcase import normalize_metrics_for_display, parse_design_prompt, run_prompt_design


PROMPTS = [
    {
        "id": "A",
        "prompt": "Design a low-pass filter with 5 kHz cutoff using 10 nF capacitor.",
        "expected_case": "rc",
        "expected_constraint_keys": ["target_fc_hz", "fixed_cap_f"],
        "required_metrics": ["fc_hz"],
        "optional_metrics": ["bandwidth_hz"],
    },
    {
        "id": "B",
        "prompt": "Design an RLC bandpass filter centered at 10 kHz with Q of 2.",
        "expected_case": "rlc_bandpass",
        "expected_constraint_keys": ["target_center_hz", "quality_factor_q"],
        "required_metrics_any": ["center_hz", "center_freq_hz", "peak_freq_hz", "peak_frequency_hz"],
        "optional_metrics": ["q_factor", "bandwidth_hz"],
    },
    {
        "id": "C",
        "prompt": "Design a common-source amplifier with 20 dB gain, 2 MHz bandwidth, under 4 mW.",
        "expected_case": "common_source",
        "expected_constraint_keys": ["target_gain_db", "target_bw_hz", "power_limit_mw"],
        "required_metrics": ["gain_db"],
        "optional_metrics": ["bandwidth_hz", "power_mw"],
    },
    {
        "id": "D",
        "prompt": "Design a current mirror with 100 uA reference current and 2x mirror ratio.",
        "expected_case": "mirror",
        "expected_constraint_keys": ["reference_current_a", "mirror_ratio"],
        "required_metrics": [
            "reference_current_a",
            "output_current_a",
            "mirror_ratio_measured",
            "ratio_error_percent",
        ],
    },
    {
        "id": "E",
        "prompt": "Design an op amp with high gain, 5 MHz UGBW, and 2 pF load.",
        "expected_case": "folded_cascode_opamp",
        "expected_constraint_keys": ["target_ugbw_hz", "load_cap_f"],
        "required_metrics": ["gain_db", "ugbw_hz"],
        "optional_metrics": ["phase_margin_deg", "power_mw"],
    },
]


def _present(value):
    if value is None:
        return False
    if isinstance(value, str) and not value.strip():
        return False
    return True


def _check_artifacts(result):
    raw = result.get("raw_paths") or {}
    artifacts = result.get("artifacts") or {}
    findings = {}

    findings["generated_sp"] = bool(_present(raw.get("generated_sp")) and Path(raw["generated_sp"]).exists())

    schematic_paths = []
    if _present(raw.get("schematic")):
        schematic_paths.append(raw["schematic"])
    schematic_paths.extend(artifacts.get("schematic") or [])
    findings["schematic"] = any(Path(p).exists() for p in schematic_paths if p)

    plot_paths = []
    for key in ("ac_plot", "dc_plot", "tran_plot"):
        if _present(raw.get(key)):
            plot_paths.append(raw[key])
    for key in ("ac_plot", "dc_plot", "transient_plot"):
        plot_paths.extend(artifacts.get(key) or [])
    findings["plot"] = any(Path(p).exists() for p in plot_paths if p)

    final_report = raw.get("final_report") or ""
    findings["final_report"] = bool(final_report and Path(final_report).exists())

    artifact_dir = ""
    if final_report:
        artifact_dir = str(Path(final_report).parent)
    findings["artifact_dir"] = artifact_dir
    return findings


def validate_case(case):
    parsed = parse_design_prompt(case["prompt"])
    parsed_case = parsed.get("selected_case")
    parsed_constraints = parsed.get("constraints") or {}
    case_ok = parsed_case == case["expected_case"]
    missing_constraint_keys = [
        key for key in case.get("expected_constraint_keys", []) if key not in parsed_constraints
    ]

    result = run_prompt_design(case["prompt"], "Offline deterministic")
    metrics = result.get("metrics") or {}
    normalized = normalize_metrics_for_display(result, parsed_constraints=parsed_constraints)

    artifact_findings = _check_artifacts(result)

    required = case.get("required_metrics") or []
    optional = case.get("optional_metrics") or []
    required_any = case.get("required_metrics_any") or []

    metric_sources = {**metrics, **normalized}

    missing_required = [key for key in required if not _present(metric_sources.get(key))]
    if required_any:
        if not any(_present(metric_sources.get(key)) for key in required_any):
            missing_required.append("(" + " | ".join(required_any) + ")")
    optional_present = [key for key in optional if _present(metric_sources.get(key))]

    verdict = result.get("verdict") or "n/a"
    artifact_dir = artifact_findings.get("artifact_dir") or ""

    overall_ok = (
        case_ok
        and not missing_constraint_keys
        and not missing_required
        and artifact_findings["generated_sp"]
        and artifact_findings["schematic"]
        and artifact_findings["plot"]
        and artifact_findings["final_report"]
    )

    return {
        "id": case["id"],
        "prompt": case["prompt"],
        "case": parsed_case,
        "expected_case": case["expected_case"],
        "case_ok": case_ok,
        "constraints_present": [k for k in case.get("expected_constraint_keys", []) if k in parsed_constraints],
        "missing_constraints": missing_constraint_keys,
        "metrics_found": [k for k, v in metric_sources.items() if _present(v)],
        "missing_required_metrics": missing_required,
        "optional_metrics_present": optional_present,
        "verdict": verdict,
        "artifact_dir": artifact_dir,
        "schematic_status": (result.get("manifest") or {}).get("schematic_status") or normalized.get("schematic_status") or "",
        "ok": overall_ok,
        "artifact_findings": artifact_findings,
        "normalized_metrics": normalized,
    }


def _truncate(text: str, width: int) -> str:
    text = str(text)
    if len(text) <= width:
        return text.ljust(width)
    return text[: max(0, width - 1)] + "…"


def print_table(rows):
    headers = ["id", "prompt", "case", "case_ok", "constraints", "metrics_required", "verdict", "artifact_dir"]
    widths = [3, 60, 22, 8, 32, 28, 22, 60]
    print(" | ".join(_truncate(h, w) for h, w in zip(headers, widths)))
    print("-+-".join("-" * w for w in widths))
    for row in rows:
        constraints = ",".join(row["constraints_present"])
        if row["missing_constraints"]:
            constraints += "|MISSING:" + ",".join(row["missing_constraints"])
        missing = ",".join(row["missing_required_metrics"]) or "ok"
        line = [
            row["id"],
            row["prompt"],
            row["case"],
            "ok" if row["case_ok"] else "MISMATCH",
            constraints,
            missing,
            row["verdict"],
            row["artifact_dir"],
        ]
        print(" | ".join(_truncate(value, w) for value, w in zip(line, widths)))


def main():
    rows = []
    for case in PROMPTS:
        try:
            rows.append(validate_case(case))
        except Exception as exc:
            rows.append(
                {
                    "id": case["id"],
                    "prompt": case["prompt"],
                    "case": "ERROR",
                    "expected_case": case["expected_case"],
                    "case_ok": False,
                    "constraints_present": [],
                    "missing_constraints": ["RAISED"],
                    "metrics_found": [],
                    "missing_required_metrics": [f"exception:{exc}"],
                    "optional_metrics_present": [],
                    "verdict": "exception",
                    "artifact_dir": "",
                    "ok": False,
                    "artifact_findings": {},
                }
            )

    print()
    print_table(rows)
    print()

    failures = [row for row in rows if not row["ok"]]
    print(f"Summary: {len(rows) - len(failures)}/{len(rows)} prompts fully verified.")
    for row in failures:
        print(
            f"- FAIL {row['id']} ({row['case']}): "
            f"missing_constraints={row['missing_constraints']} "
            f"missing_required_metrics={row['missing_required_metrics']} "
            f"artifacts={row['artifact_findings']}"
        )

    if failures:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
