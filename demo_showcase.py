#!/usr/bin/env python3
import argparse
import csv
import json
import os
import tempfile
from datetime import datetime
from pathlib import Path

from core.demo_catalog import get_demo_case, list_demo_cases, slugify_label, stable_demo_cases
from core.demo_safe import summarize_sizing
from core.showcase_artifacts import organize_showcase_latest, row_from_final_state, sweep_group_from_output
from core.sweep_registry import (
    apply_sweep_value,
    default_sweep_parameter,
    evaluate_sweep_outcome,
    extract_measured_metric,
    get_case_sweep_schema,
    sweepable_parameters,
)
from main import run_case

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "i13-mplconfig"))


CASE_ALIASES = {"rc_lowpass": "rc", "current_mirror": "mirror"}


def parse_sweep(value: str) -> tuple[str, list[float]]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("Sweep must look like name=v1,v2,v3")
    key, raw_values = value.split("=", 1)
    values = [float(item) for item in raw_values.split(",") if item.strip()]
    if not key or not values:
        raise argparse.ArgumentTypeError("Sweep must include a parameter name and at least one value")
    return key.strip(), values


def resolve_case(case_name: str) -> str:
    return CASE_ALIASES.get((case_name or "").strip().lower(), case_name)


def _default_sponsor_case_list() -> list[str]:
    cases = stable_demo_cases()
    if cases:
        return cases
    # Safety fallback if readiness metadata is missing.
    return ["rc", "rlc_bandpass", "mirror", "common_source", "folded_cascode_opamp"]


def _default_sponsor_sweeps() -> list[tuple[str, str, list[float]]]:
    sweeps = []
    for case_name in _default_sponsor_case_list():
        schema = get_case_sweep_schema(case_name)
        param = default_sweep_parameter(case_name)
        if not schema or not param:
            continue
        values = ((schema.get("sweep_parameters") or {}).get(param) or {}).get("default_points") or []
        if len(values) >= 2:
            sweeps.append((case_name, param, [float(item) for item in values[:3]]))
    return sweeps


def run_sweep(case_name: str, sweep_key: str, values: list[float], output_dir: str = None, update_latest: bool = True):
    resolved_case = resolve_case(case_name)
    base_case = get_demo_case(resolved_case)
    schema = get_case_sweep_schema(resolved_case)
    if not schema:
        raise ValueError(
            f"Sweeps are not declared for case '{resolved_case}'. "
            "Use a case with an explicit sweep schema to avoid misleading verification."
        )
    allowed = set(sweepable_parameters(resolved_case))
    if sweep_key not in allowed:
        raise ValueError(
            f"Sweep parameter '{sweep_key}' is not supported for case '{resolved_case}'. "
            f"Supported parameters: {', '.join(sorted(allowed)) or 'none'}."
        )

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(output_dir or Path("artifacts") / "showcase_sweeps" / f"{stamp}_{resolved_case}_{sweep_key}")
    root.mkdir(parents=True, exist_ok=True)

    rows = []
    for value in values:
        constraints = apply_sweep_value(
            resolved_case,
            dict(base_case.get("constraints") or {}),
            sweep_key,
            float(value),
        )
        specification = f"{base_case.get('specification')} Sweep override: {sweep_key}={value:g}."
        artifact_label = f"{base_case.get('artifact_label')}_{sweep_key}_{slugify_label(str(value))}"
        override = {
            "specification": specification,
            "constraints": constraints,
            "artifact_label": artifact_label,
        }
        print(f"\n[showcase] Running {resolved_case} with {sweep_key}={value:g}")
        final_state = run_case(resolved_case, case_override=override)
        sim = final_state.get("simulation_results") or {}
        metric_name, measured = extract_measured_metric(final_state, resolved_case, sweep_key)
        row = {
            "case": resolved_case,
            "sweep_parameter": sweep_key,
            "requested_spec": value,
            "measured_metric": metric_name or "",
            "measured_result": measured if measured is not None else "",
            "component_values": "; ".join(summarize_sizing(final_state.get("sizing") or {})),
            "artifact_dir": sim.get("artifact_dir") or "",
            "generated_netlist": sim.get("saved_netlist_path") or "",
            "schematic_png": sim.get("schematic_png_path") or "",
            "ac_plot": sim.get("ac_plot") or "",
            "dc_plot": sim.get("dc_plot") or "",
            "tran_plot": sim.get("tran_plot") or "",
            "final_report": str(Path(sim.get("artifact_dir") or ".") / "final_report.txt") if sim.get("artifact_dir") else "",
            "backend_used": ((sim.get("netlist_backend_metadata") or {}).get("backend_used") or ""),
            "fallback_reason": ((sim.get("netlist_backend_metadata") or {}).get("fallback_reason") or ""),
        }
        sweep_eval = evaluate_sweep_outcome(final_state, resolved_case, sweep_key, row=row)
        row["pass_fail"] = sweep_eval["status"]
        row["missing_artifacts"] = ";".join(sweep_eval.get("missing_artifacts") or [])
        row["verification_status"] = sweep_eval.get("verification_status") or ""
        row["overall_verdict"] = sweep_eval.get("overall_verdict") or ""
        rows.append(row)

    table_path = root / "comparison_table.csv"
    summary_path = root / "comparison_summary.md"
    plot_path = root / "comparison_plot.png"
    index_path = root / "run_index.json"
    write_csv(table_path, rows)
    write_summary(summary_path, rows, resolved_case, sweep_key)
    write_plot(plot_path, rows, sweep_key)
    index_path.write_text(json.dumps({"rows": rows}, indent=2, sort_keys=True) + "\n")
    if update_latest:
        organize_showcase_latest(
            command=f"venv/bin/python3 demo_showcase.py --case {case_name} --sweep {sweep_key}={','.join(f'{item:g}' for item in values)}",
            sweep_groups=[sweep_group_from_output(f"{resolved_case}_{sweep_key}", str(root), rows)],
            architecture_summary=(
                "This standalone sweep exercised the hybrid analog design flow: topology and sizing agents interpret the spec, "
                "NetlistAgent routes through optional LLM backends with deterministic fallback, ngspice produces evidence, "
                "and deterministic extractors generate plots, metrics, and reports."
            ),
            clean=True,
        )

    print("\n[showcase] Sweep complete.")
    print(f"comparison_summary: {summary_path}")
    print(f"comparison_table:   {table_path}")
    print(f"comparison_plot:    {plot_path}")
    for row in rows:
        print(f"- {row['requested_spec']}: netlist={row['generated_netlist']} report={row['final_report']}")
    return rows, root


def run_all_safe(output_dir: str = None, include_sweeps: bool = True):
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    root = Path(output_dir or Path("artifacts") / "showcase_runs" / "_latest_working" / f"{stamp}_all_safe")
    root.mkdir(parents=True, exist_ok=True)

    all_safe_cases = _default_sponsor_case_list()
    all_safe_sweeps = _default_sponsor_sweeps()

    print("=== Sponsor Safe Showcase Bundle ===")
    print("Cases: " + ", ".join(all_safe_cases))
    print(f"Working output dir: {root}")

    case_rows = []
    for case_name in all_safe_cases:
        print(f"\n[showcase] Running safe case: {case_name}")
        final_state = run_case(case_name)
        case_rows.append(row_from_final_state(case_name, final_state))

    sweep_groups = []
    if include_sweeps:
        for case_name, sweep_key, values in all_safe_sweeps:
            sweep_dir = root / f"{resolve_case(case_name)}_{sweep_key}"
            rows, sweep_root = run_sweep(
                case_name,
                sweep_key,
                values,
                output_dir=str(sweep_dir),
                update_latest=False,
            )
            sweep_groups.append(
                sweep_group_from_output(
                    f"{case_name}_{sweep_key}",
                    str(sweep_root),
                    rows,
                )
            )

    manifest = organize_showcase_latest(
        command="venv/bin/python3 demo_showcase.py --all-safe",
        case_rows=case_rows,
        sweep_groups=sweep_groups,
        architecture_summary=(
            "This sponsor-safe bundle uses deterministic topology selection, sizing equations, and netlist templates for correctness, "
            "then records optional Hugging Face/OpenAI backend provenance when those services are enabled. "
            "Each case exposes the multi-agent chain from specification parsing through topology, sizing, netlist generation, simulation, "
            "metrics extraction, verification, refinement guidance, and report/artifact generation."
        ),
        clean=True,
    )

    print("\n[showcase] All-safe bundle complete.")
    print("summary:  artifacts/showcase_runs/latest/summary.md")
    print("index:    artifacts/showcase_runs/latest/index.html")
    print("manifest: artifacts/showcase_runs/latest/artifact_manifest.json")
    return manifest


def write_csv(path: Path, rows: list[dict]):
    fieldnames = [
        "case",
        "sweep_parameter",
        "requested_spec",
        "measured_metric",
        "measured_result",
        "pass_fail",
        "component_values",
        "artifact_dir",
        "generated_netlist",
        "schematic_png",
        "ac_plot",
        "dc_plot",
        "tran_plot",
        "final_report",
        "backend_used",
        "fallback_reason",
        "verification_status",
        "overall_verdict",
        "missing_artifacts",
    ]
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def write_summary(path: Path, rows: list[dict], case_name: str, sweep_key: str):
    lines = [
        f"# Showcase Sweep: {case_name}",
        "",
        f"- Sweep parameter: `{sweep_key}`",
        f"- Runs: {len(rows)}",
        "",
        "| requested spec | measured result | pass/fail | backend | artifact folder |",
        "|---:|---:|---|---|---|",
    ]
    for row in rows:
        measured = row["measured_result"]
        measured_text = f"{measured:.6g}" if isinstance(measured, float) else str(measured or "n/a")
        lines.append(
            f"| {float(row['requested_spec']):.6g} | {row['measured_metric']}={measured_text} | "
            f"{row['pass_fail']} | {row['backend_used'] or 'n/a'} | `{row['artifact_dir']}` |"
        )
    lines.extend(["", "## Component Values", ""])
    for row in rows:
        lines.append(f"- `{sweep_key}={float(row['requested_spec']):.6g}`: {row['component_values'] or 'n/a'}")
    lines.extend(["", "## Files To Open", ""])
    for row in rows:
        lines.append(f"- `{sweep_key}={float(row['requested_spec']):.6g}`")
        lines.append(f"  - final_report: `{row['final_report']}`")
        lines.append(f"  - generated.sp: `{row['generated_netlist']}`")
        lines.append(f"  - schematic: `{row['schematic_png'] or 'n/a'}`")
        if row["ac_plot"]:
            lines.append(f"  - ac_plot: `{row['ac_plot']}`")
        if row["dc_plot"]:
            lines.append(f"  - dc_plot: `{row['dc_plot']}`")
        if row["tran_plot"]:
            lines.append(f"  - tran_plot: `{row['tran_plot']}`")
    path.write_text("\n".join(lines) + "\n")


def write_plot(path: Path, rows: list[dict], sweep_key: str):
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception:
        path.write_text("matplotlib unavailable; comparison plot not generated\n")
        return
    xs = [float(row["requested_spec"]) for row in rows if row["measured_result"] != ""]
    ys = [float(row["measured_result"]) for row in rows if row["measured_result"] != ""]
    fig, ax = plt.subplots(figsize=(7, 4.5))
    if xs and ys:
        ax.plot(xs, ys, marker="o", linewidth=2)
        ax.set_xlabel(sweep_key)
        ax.set_ylabel(rows[0].get("measured_metric") or "measured result")
        ax.grid(True, alpha=0.3)
        ax.set_title("Parameter-dependent measured result")
    else:
        ax.axis("off")
        ax.text(
            0.5,
            0.55,
            "No measured sweep results available",
            ha="center",
            va="center",
            fontsize=14,
            weight="bold",
        )
        ax.text(
            0.5,
            0.42,
            "Simulation may be unavailable; reports show honest partial status.",
            ha="center",
            va="center",
            fontsize=10,
        )
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description="Run a live parameter sweep showcase demo")
    parser.add_argument("--all-safe", action="store_true", help="Generate the canonical sponsor-safe latest artifact bundle")
    parser.add_argument("--case", help="Demo case, e.g. rc_lowpass, common_source, mos_buffer")
    parser.add_argument("--sweep", type=parse_sweep, help="Parameter sweep, e.g. target_fc_hz=500,1000,5000")
    parser.add_argument("--output-dir", help="Directory for comparison_summary/table/plot")
    parser.add_argument("--list-cases", action="store_true", help="Print available cases before running")
    parser.add_argument("--no-sweeps", action="store_true", help="With --all-safe, skip parameter sweeps")
    args = parser.parse_args()
    if args.list_cases:
        for item in list_demo_cases():
            params = sweepable_parameters(item["key"])
            print(
                f"{item['key']}: {item['display_name']} "
                f"(readiness={item.get('readiness')}, sweeps={','.join(params) if params else 'none'})"
            )
        if not args.all_safe and not (args.case and args.sweep):
            return
    if args.all_safe:
        run_all_safe(output_dir=args.output_dir, include_sweeps=not args.no_sweeps)
        return
    if not args.case or not args.sweep:
        parser.error("--case and --sweep are required unless --all-safe is used")
    sweep_key, values = args.sweep
    run_sweep(args.case, sweep_key, values, output_dir=args.output_dir)


if __name__ == "__main__":
    main()
