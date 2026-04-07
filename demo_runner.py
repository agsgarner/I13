import json
import os
from datetime import datetime

from core.demo_catalog import describe_case_for_artifacts, get_demo_case, list_demo_cases, resolve_case_name, slugify_label
from main import format_final_report, run_case


def _selected_cases():
    raw = os.getenv("DESIGN_CASES", "").strip()
    if raw:
        return [resolve_case_name(item) for item in raw.split(",") if item.strip()]

    limit = os.getenv("DEMO_LIMIT", "").strip()
    cases = [item["key"] for item in list_demo_cases()]
    if limit:
        return cases[: max(1, int(limit))]
    return cases


def _batch_slug(cases):
    if not cases:
        return "empty-demo-batch"
    if len(cases) == 1:
        case = get_demo_case(cases[0])
        return f"single_{describe_case_for_artifacts(case)}"
    return f"batch_{len(cases)}_cases_{slugify_label('-'.join(cases[:3]))}"


def main():
    cases = _selected_cases()
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join("artifacts", "demo_runs", f"{stamp}_{_batch_slug(cases)}")
    os.makedirs(out_dir, exist_ok=True)

    summary = []
    for case_name in cases:
        final_state = run_case(case_name)
        report = format_final_report(case_name, final_state)
        with open(os.path.join(out_dir, f"{case_name}.txt"), "w") as f:
            f.write(report + "\n")

        sim = final_state.get("simulation_results") or {}
        summary.append(
            {
                "case": case_name,
                "display_name": (final_state.get("case_metadata") or {}).get("display_name"),
                "simulation_plan": (final_state.get("case_metadata") or {}).get("simulation_plan"),
                "status": final_state.get("status"),
                "topology": final_state.get("selected_topology"),
                "artifact_dir": sim.get("artifact_dir"),
                "ac_plot": sim.get("ac_plot"),
                "tran_plot": sim.get("tran_plot"),
                "dc_plot": sim.get("dc_plot"),
                "gain_db": sim.get("gain_db"),
                "bandwidth_hz": sim.get("bandwidth_hz"),
                "fc_hz": sim.get("fc_hz"),
                "iout_a": sim.get("iout_a"),
                "vref_v": sim.get("vref_v"),
                "oscillation_hz": sim.get("oscillation_hz"),
                "write_ok": sim.get("write_ok"),
                "history_tail": (final_state.get("history") or [])[-5:],
            }
        )

    with open(os.path.join(out_dir, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)

    with open(os.path.join(out_dir, "README.txt"), "w") as f:
        f.write("Demo batch artifact guide\n")
        f.write(f"Batch folder: {out_dir}\n")
        f.write("Each simulation artifact folder now includes case and topology labels plus the planned analyses.\n")
        f.write("Pattern: <case>/<case>__<topology>__<analyses>__attempt-XX__<timestamp>\n\n")
        for item in summary:
            f.write(
                f"- {item['case']}: {item.get('display_name') or 'n/a'} | "
                f"status={item.get('status')} | artifact_dir={item.get('artifact_dir')}\n"
            )

    print(f"Wrote batch demo artifacts to {out_dir}")
    for item in summary:
        print(f"- {item['case']}: {item['status']} ({item['artifact_dir']})")


if __name__ == "__main__":
    main()
