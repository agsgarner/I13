import json
import math
import os
import sys
import time
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from core.demo_catalog import get_demo_case, get_demo_profile, list_demo_cases, resolve_case_name, slugify_label
from main import build_llm, run_case


def pass_at_k(total_samples: int, successful_samples: int, k: int) -> float:
    n = max(0, int(total_samples))
    c = max(0, min(int(successful_samples), n))
    k = max(1, int(k))
    if n == 0:
        return 0.0
    if c == 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - (math.comb(n - c, k) / math.comb(n, k))


def _parse_ks(raw: str):
    values = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(max(1, int(part)))
        except Exception:
            continue
    return values or [1, 3, 5]


def _mean(values):
    clean = [float(item) for item in values if item is not None]
    if not clean:
        return None
    return sum(clean) / len(clean)


def _weighted_average(items, value_key, weight_key):
    weighted_sum = 0.0
    total_weight = 0.0
    for item in items:
        value = item.get(value_key)
        weight = item.get(weight_key)
        if value is None or weight is None:
            continue
        weight = float(weight)
        if weight <= 0:
            continue
        weighted_sum += float(value) * weight
        total_weight += weight
    if total_weight <= 0:
        return None
    return weighted_sum / total_weight


def _selected_cases():
    profile = os.getenv("BENCH_PROFILE", "").strip().lower()
    if profile:
        return get_demo_profile(profile)

    raw_cases = os.getenv("BENCH_CASES", "").strip()
    if raw_cases:
        return [resolve_case_name(item) for item in raw_cases.split(",") if item.strip()]

    default_cases = [item["key"] for item in list_demo_cases() if item.get("ti_priority") in {"high", "medium"}]
    limit = os.getenv("BENCH_LIMIT", "").strip()
    if limit:
        return default_cases[: max(1, int(limit))]
    return default_cases


def _sample_override(case: dict, sample_idx: int, jitter: bool):
    constraints = dict(case.get("constraints") or {})
    constraints["sample_id"] = sample_idx

    override = {"constraints": constraints}
    if jitter:
        override["specification"] = (
            f"{case.get('specification', '')}\n"
            f"Sampling context: benchmark sample {sample_idx + 1}."
        )
    return override


def _sample_record(case_name: str, final_state: dict, duration_s: float):
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    history = final_state.get("history") or []
    llm_calls = [item for item in history if item.get("event") == "llm_call"]
    llm_calls_ok = 0
    llm_calls_by_agent = {}
    llm_calls_by_task = {}
    for call in llm_calls:
        payload = call.get("data") or {}
        agent = payload.get("agent") or "unknown_agent"
        task = payload.get("task") or "unknown_task"
        llm_calls_by_agent[agent] = llm_calls_by_agent.get(agent, 0) + 1
        llm_calls_by_task[task] = llm_calls_by_task.get(task, 0) + 1
        if payload.get("ok") is True:
            llm_calls_ok += 1

    known_checks = verification.get("known_checks") or 0
    passes = verification.get("passes") or 0
    verification_pass_rate = (passes / known_checks) if known_checks > 0 else None
    netlist_stage_report = final_state.get("netlist_stage_report") or sim.get("netlist_stage_report") or {}
    refinement_loops = int(final_state.get("iteration", 0) or 0)

    success = (
        final_state.get("status") == "design_validated"
        and verification.get("overall_pass") is True
    )

    return {
        "case": case_name,
        "status": final_state.get("status"),
        "topology": final_state.get("selected_topology"),
        "selected_topologies": final_state.get("selected_topologies"),
        "iterations": refinement_loops,
        "converged_first_pass": bool(success and refinement_loops == 0),
        "duration_s": duration_s,
        "success": bool(success),
        "verification": {
            "passes": verification.get("passes"),
            "fails": verification.get("fails"),
            "unknown": verification.get("unknown"),
            "known_checks": known_checks,
            "total_checks": verification.get("total_checks"),
            "coverage_ratio": verification.get("coverage_ratio"),
            "overall_pass": verification.get("overall_pass"),
            "pass_rate_on_known": verification_pass_rate,
        },
        "metrics": {
            "gain_db": sim.get("gain_db"),
            "bandwidth_hz": sim.get("bandwidth_hz"),
            "ugbw_hz": sim.get("ugbw_hz"),
            "fc_hz": sim.get("fc_hz"),
            "power_mw": sim.get("power_mw"),
            "iout_a": sim.get("iout_a"),
            "vref_v": sim.get("vref_v"),
            "decision_delay_s": sim.get("decision_delay_s"),
            "oscillation_hz": sim.get("oscillation_hz"),
        },
        "plot_validation_summary": sim.get("plot_validation_summary"),
        "llm_call_count": len(llm_calls),
        "llm_call_success_count": llm_calls_ok,
        "llm_call_success_rate": (llm_calls_ok / len(llm_calls)) if llm_calls else None,
        "llm_calls_by_agent": llm_calls_by_agent,
        "llm_calls_by_task": llm_calls_by_task,
        "composite": {
            "stage_count_match": netlist_stage_report.get("stage_count_match"),
            "topology_order_match": netlist_stage_report.get("topology_order_match"),
            "planned_stage_count": netlist_stage_report.get("planned_stage_count"),
            "realized_stage_count": netlist_stage_report.get("realized_stage_count"),
            "continuity_issues": netlist_stage_report.get("continuity_issues"),
        },
        "artifact_dir": sim.get("artifact_dir"),
    }


def _aggregate_case(case_name: str, samples: list, ks: list):
    total = len(samples)
    successes = sum(1 for item in samples if item.get("success"))
    avg_runtime = sum(float(item.get("duration_s", 0.0)) for item in samples) / max(total, 1)
    avg_iterations = sum(float(item.get("iterations", 0.0)) for item in samples) / max(total, 1)

    pass_rates = [
        item.get("verification", {}).get("pass_rate_on_known")
        for item in samples
        if item.get("verification", {}).get("pass_rate_on_known") is not None
    ]
    coverage = [
        item.get("verification", {}).get("coverage_ratio")
        for item in samples
        if item.get("verification", {}).get("coverage_ratio") is not None
    ]
    llm_success_rates = [
        item.get("llm_call_success_rate")
        for item in samples
        if item.get("llm_call_success_rate") is not None
    ]
    stage_count_match_rates = [
        1.0 if item.get("composite", {}).get("stage_count_match") is True else 0.0
        for item in samples
        if item.get("composite", {}).get("stage_count_match") is not None
    ]
    stage_order_match_rates = [
        1.0 if item.get("composite", {}).get("topology_order_match") is True else 0.0
        for item in samples
        if item.get("composite", {}).get("topology_order_match") is not None
    ]
    first_pass_successes = sum(1 for item in samples if item.get("converged_first_pass"))

    case_summary = {
        "case": case_name,
        "num_samples": total,
        "successful_samples": successes,
        "success_rate": successes / max(total, 1),
        "first_pass_success_rate": first_pass_successes / max(total, 1),
        "avg_runtime_s": avg_runtime,
        "avg_iterations": avg_iterations,
        "avg_verification_pass_rate": (sum(pass_rates) / len(pass_rates)) if pass_rates else None,
        "avg_verification_coverage": (sum(coverage) / len(coverage)) if coverage else None,
        "avg_llm_calls_per_sample": _mean(item.get("llm_call_count") for item in samples),
        "avg_llm_success_rate": _mean(llm_success_rates),
        "composite_stage_count_match_rate": _mean(stage_count_match_rates),
        "composite_stage_order_match_rate": _mean(stage_order_match_rates),
        "pass_at_k": {f"k={k}": pass_at_k(total, successes, k) for k in ks},
    }

    forced_topology = (get_demo_case(case_name) or {}).get("forced_topology")
    if forced_topology:
        matches = sum(1 for item in samples if item.get("topology") == forced_topology)
        case_summary["topology_match_rate"] = matches / max(total, 1)
        case_summary["forced_topology"] = forced_topology
    return case_summary


def _aggregate_overall(case_summaries: list, ks: list):
    total_samples = sum(item.get("num_samples", 0) for item in case_summaries)
    successful_samples = sum(item.get("successful_samples", 0) for item in case_summaries)
    runtime_values = [item.get("avg_runtime_s") for item in case_summaries if item.get("avg_runtime_s") is not None]

    overall = {
        "total_cases": len(case_summaries),
        "total_samples": total_samples,
        "successful_samples": successful_samples,
        "sample_success_rate": successful_samples / max(total_samples, 1),
        "first_pass_success_rate": _weighted_average(case_summaries, "first_pass_success_rate", "num_samples"),
        "pass_at_k": {f"k={k}": pass_at_k(total_samples, successful_samples, k) for k in ks},
        "avg_case_runtime_s": (sum(runtime_values) / len(runtime_values)) if runtime_values else None,
        "avg_case_iterations": _weighted_average(case_summaries, "avg_iterations", "num_samples"),
        "avg_verification_pass_rate": _weighted_average(case_summaries, "avg_verification_pass_rate", "num_samples"),
        "avg_verification_coverage": _weighted_average(case_summaries, "avg_verification_coverage", "num_samples"),
        "avg_llm_calls_per_sample": _weighted_average(case_summaries, "avg_llm_calls_per_sample", "num_samples"),
        "avg_llm_success_rate": _weighted_average(case_summaries, "avg_llm_success_rate", "num_samples"),
        "composite_stage_count_match_rate": _weighted_average(case_summaries, "composite_stage_count_match_rate", "num_samples"),
        "composite_stage_order_match_rate": _weighted_average(case_summaries, "composite_stage_order_match_rate", "num_samples"),
    }
    return overall


def run_benchmark():
    cases = _selected_cases()
    if not cases:
        raise SystemExit("No benchmark cases selected. Set BENCH_CASES or BENCH_PROFILE.")

    samples_per_case = max(1, int(os.getenv("BENCH_SAMPLES", "5")))
    ks = _parse_ks(os.getenv("BENCH_KS", "1,3,5"))
    jitter = os.getenv("BENCH_PROMPT_JITTER", "0").strip() == "1"

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    case_slug = slugify_label("-".join(cases[:3]))
    out_dir = os.path.join("artifacts", "benchmarks", f"{stamp}_n{samples_per_case}_{case_slug}")
    os.makedirs(out_dir, exist_ok=True)

    llm = build_llm()
    benchmark_samples = {}
    case_summaries = []

    for case_name in cases:
        case = get_demo_case(case_name)
        records = []
        print(f"[Benchmark] {case_name}: {samples_per_case} samples")
        for sample_idx in range(samples_per_case):
            override = _sample_override(case, sample_idx, jitter=jitter)
            start = time.time()
            final_state = run_case(case_name, case_override=override, llm_override=llm)
            duration_s = time.time() - start
            record = _sample_record(case_name, final_state, duration_s)
            record["sample_index"] = sample_idx
            records.append(record)
            status = record.get("status")
            ok = "PASS" if record.get("success") else "FAIL"
            print(
                f"  - sample {sample_idx + 1}/{samples_per_case}: "
                f"{ok} status={status} topology={record.get('topology')} "
                f"runtime={duration_s:.2f}s"
            )

        benchmark_samples[case_name] = records
        case_summaries.append(_aggregate_case(case_name, records, ks=ks))

    overall = _aggregate_overall(case_summaries, ks=ks)

    report = {
        "config": {
            "cases": cases,
            "samples_per_case": samples_per_case,
            "ks": ks,
            "prompt_jitter": jitter,
            "timestamp": stamp,
        },
        "overall": overall,
        "case_summaries": case_summaries,
        "samples": benchmark_samples,
    }

    with open(os.path.join(out_dir, "benchmark_summary.json"), "w") as handle:
        json.dump(report, handle, indent=2)

    with open(os.path.join(out_dir, "benchmark_summary.md"), "w") as handle:
        handle.write("# Benchmark Summary\n\n")
        handle.write(f"- Cases: {', '.join(cases)}\n")
        handle.write(f"- Samples per case: {samples_per_case}\n")
        handle.write(f"- Overall sample success rate: {overall['sample_success_rate']:.3f}\n")
        if overall.get("first_pass_success_rate") is not None:
            handle.write(f"- Overall first-pass success rate: {overall['first_pass_success_rate']:.3f}\n")
        for key, value in overall.get("pass_at_k", {}).items():
            handle.write(f"- Overall {key}: {value:.3f}\n")
        if overall.get("avg_llm_calls_per_sample") is not None:
            handle.write(f"- Avg LLM calls/sample: {overall['avg_llm_calls_per_sample']:.3f}\n")
        if overall.get("avg_llm_success_rate") is not None:
            handle.write(f"- Avg LLM call success-rate: {overall['avg_llm_success_rate']:.3f}\n")
        if overall.get("composite_stage_count_match_rate") is not None:
            handle.write(
                f"- Composite stage-count match-rate: {overall['composite_stage_count_match_rate']:.3f}\n"
            )
        if overall.get("composite_stage_order_match_rate") is not None:
            handle.write(
                f"- Composite stage-order match-rate: {overall['composite_stage_order_match_rate']:.3f}\n"
            )
        handle.write("\n## Per-Case\n\n")
        for item in case_summaries:
            handle.write(f"### {item['case']}\n")
            handle.write(f"- Success rate: {item['success_rate']:.3f}\n")
            handle.write(f"- First-pass success rate: {item['first_pass_success_rate']:.3f}\n")
            for key, value in item.get("pass_at_k", {}).items():
                handle.write(f"- {key}: {value:.3f}\n")
            if item.get("topology_match_rate") is not None:
                handle.write(f"- Topology match rate: {item['topology_match_rate']:.3f}\n")
            if item.get("avg_llm_calls_per_sample") is not None:
                handle.write(f"- Avg LLM calls/sample: {item['avg_llm_calls_per_sample']:.3f}\n")
            if item.get("avg_llm_success_rate") is not None:
                handle.write(f"- Avg LLM call success-rate: {item['avg_llm_success_rate']:.3f}\n")
            if item.get("composite_stage_count_match_rate") is not None:
                handle.write(
                    f"- Composite stage-count match-rate: {item['composite_stage_count_match_rate']:.3f}\n"
                )
            if item.get("composite_stage_order_match_rate") is not None:
                handle.write(
                    f"- Composite stage-order match-rate: {item['composite_stage_order_match_rate']:.3f}\n"
                )
            handle.write(f"- Avg runtime: {item.get('avg_runtime_s', 0.0):.2f}s\n\n")

    print(f"Wrote benchmark artifacts to {out_dir}")


def main():
    run_benchmark()


if __name__ == "__main__":
    main()
