import json
from pathlib import Path

from core.demo_safe import summarize_sizing


FINAL_SHOWCASE_PRIMARY_COMMAND = "python3 main.py showcase"
FINAL_SHOWCASE_BACKUP_COMMAND = "python3 main.py showcase-backup"


FINAL_SHOWCASE_CASES = [
    "rc",
    "mirror",
    "common_source",
    "folded_cascode_opamp",
    "bandgap_reference",
    "comparator",
]


FINAL_SHOWCASE_CASE_DETAILS = {
    "rc": {
        "showcase_role": "Passive baseline",
        "demonstrates": "A simple low-pass section with clean AC and transient behavior.",
        "why_selected": "It converges quickly, hits the cutoff target tightly, and gives an easy baseline for the rest of the showcase.",
        "recommended_visual_keys": ["ac_plot", "tran_plot"],
    },
    "mirror": {
        "showcase_role": "Bias generation",
        "demonstrates": "A transistor-level current mirror with DC current-copy verification.",
        "why_selected": "It is a reliable bias-building-block case with clear sizing, compliance, and current-copy metrics.",
        "recommended_visual_keys": ["dc_plot", "log_path"],
    },
    "common_source": {
        "showcase_role": "Single-stage gain",
        "demonstrates": "A transistor-level voltage-gain stage with iterative sizing, AC response, and transient behavior.",
        "why_selected": "It shows the multi-agent refinement loop on a familiar analog stage while still ending in a fully verified result.",
        "recommended_visual_keys": ["ac_plot", "tran_plot"],
    },
    "folded_cascode_opamp": {
        "showcase_role": "Higher-value analog block",
        "demonstrates": "A high-gain folded-cascode op-amp core with UGBW and phase-margin extraction.",
        "why_selected": "Among the advanced analog blocks, this is the strongest currently stable case with meaningful AC and transient artifacts.",
        "recommended_visual_keys": ["ac_plot", "tran_plot"],
    },
    "bandgap_reference": {
        "showcase_role": "Reference generation",
        "demonstrates": "A bandgap-style reference block with DC and transient reference behavior.",
        "why_selected": "It broadens the demo beyond gain stages and gives a technically relevant precision-reference example for TI reviewers.",
        "recommended_visual_keys": ["dc_plot", "tran_plot"],
    },
    "comparator": {
        "showcase_role": "Dynamic decision block",
        "demonstrates": "A regenerative comparator with transient decision-delay verification.",
        "why_selected": "It adds a fast dynamic block with a visually intuitive transient waveform and crisp pass/fail timing metric.",
        "recommended_visual_keys": ["tran_plot", "log_path"],
    },
}


FINAL_SHOWCASE_EXCLUDED_CASES = [
    {
        "case": "composite_gain_buffer",
        "reason": "Composite pipeline is visually interesting but currently fails verification on gain-related requirements.",
    },
    {
        "case": "ti_filter_amp_chain",
        "reason": "Three-stage chain currently fails verification and would overstate maturity in a sponsor-facing demo.",
    },
    {
        "case": "ti_three_stage_amp",
        "reason": "Current three-stage amplifier path is unstable and produces misleadingly poor measured gain.",
    },
    {
        "case": "opamp",
        "reason": "Two-stage Miller op-amp is useful but still ends in partial verification because key stability metrics remain unverified in the current sweep.",
    },
]


def _fmt_value(value, unit=""):
    if value is None:
        return "n/a"
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:.6g}{unit}"
    return f"{value}{unit}"


def _topology_reasoning(final_state: dict) -> str:
    reasoning = str(final_state.get("topology_reasoning") or "").strip()
    if reasoning:
        return reasoning
    plan = final_state.get("topology_plan") or {}
    if plan.get("mode") == "single":
        return "Selected a single topology path for the requested function."
    if plan.get("mode") == "composite":
        return "Expanded the request into a composite multi-stage topology plan."
    return "Topology reasoning was not recorded."


def _stage_status_summary(final_state: dict) -> list[dict]:
    counts = {}
    order = []
    for item in final_state.get("history") or []:
        if item.get("event") != "agent_executed":
            continue
        data = item.get("data") or {}
        agent = data.get("agent")
        if not agent:
            continue
        if agent not in counts:
            counts[agent] = {"agent": agent, "count": 0, "last_status": None}
            order.append(agent)
        counts[agent]["count"] += 1
        counts[agent]["last_status"] = data.get("status")
    return [counts[agent] for agent in order]


def _selected_visuals(sim: dict, preferred_keys: list[str]) -> list[str]:
    paths = []
    for key in preferred_keys:
        value = sim.get(key)
        if value and value not in paths:
            paths.append(value)
    return paths


def _key_metrics(final_state: dict) -> dict:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    extracted = dict(verification.get("extracted_metrics") or {})
    if extracted:
        return extracted

    metrics = {}
    for key in (
        "gain_db",
        "bandwidth_hz",
        "ugbw_hz",
        "phase_margin_deg",
        "fc_hz",
        "iout_a",
        "vref_v",
        "decision_delay_s",
        "power_mw",
    ):
        if sim.get(key) is not None:
            metrics[key] = sim.get(key)
    return metrics


def build_showcase_case_summary(case_name: str, final_state: dict, *, mode: str) -> dict:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    case_meta = final_state.get("case_metadata") or {}
    details = FINAL_SHOWCASE_CASE_DETAILS.get(case_name, {})
    requirement_rows = []
    for item in verification.get("requirement_evaluations") or []:
        requirement_rows.append(
            {
                "requirement": item.get("requirement"),
                "requested": item.get("requested"),
                "measured": item.get("measured"),
                "status": item.get("status"),
                "assessment": item.get("assessment"),
                "evidence": item.get("evidence"),
            }
        )

    return {
        "case": case_name,
        "display_name": case_meta.get("display_name") or case_name,
        "showcase_role": details.get("showcase_role", "Showcase case"),
        "demonstrates": details.get("demonstrates", ""),
        "why_selected": details.get("why_selected", ""),
        "mode": mode,
        "specification": final_state.get("specification"),
        "status": final_state.get("status"),
        "overall_verdict": verification.get("overall_verdict"),
        "verification_status": verification.get("final_status"),
        "simulation_skipped": bool(sim.get("simulation_skipped")),
        "skip_reason": sim.get("skip_reason"),
        "selected_topology": final_state.get("selected_topology"),
        "selected_topologies": final_state.get("selected_topologies") or [],
        "topology_reasoning": _topology_reasoning(final_state),
        "stage_status_summary": _stage_status_summary(final_state),
        "sizing_summary": summarize_sizing(final_state.get("sizing") or {}),
        "simulation_intent": sim.get("intent"),
        "analyses": sim.get("analyses") or [],
        "key_metrics": _key_metrics(final_state),
        "requirement_verdicts": requirement_rows,
        "artifact_dir": sim.get("artifact_dir"),
        "report_paths": {
            "final_report": str(Path(sim.get("artifact_dir") or ".") / "reports" / "final_report.txt") if sim.get("artifact_dir") else None,
            "verification_report": str(Path(sim.get("artifact_dir") or ".") / "reports" / "verification_report.json") if sim.get("artifact_dir") else None,
        },
        "recommended_visuals": _selected_visuals(
            sim,
            details.get("recommended_visual_keys", []),
        ),
    }


def render_showcase_case_markdown(summary: dict) -> str:
    lines = [
        f"# {summary.get('display_name')} ({summary.get('case')})",
        "",
        f"- Showcase role: {summary.get('showcase_role')}",
        f"- Demonstrates: {summary.get('demonstrates')}",
        f"- Why selected: {summary.get('why_selected')}",
        f"- Mode: {summary.get('mode')}",
        f"- Requested specification: {summary.get('specification')}",
        f"- Framework status: {summary.get('status')}",
        f"- Overall verdict: {summary.get('overall_verdict')}",
        f"- Verification status: {summary.get('verification_status')}",
        "",
        "## Topology Choice",
        "",
        f"- Selected topology: {summary.get('selected_topology')}",
        f"- Stage topologies: {', '.join(summary.get('selected_topologies') or []) or 'n/a'}",
        f"- Reasoning: {summary.get('topology_reasoning')}",
        "",
        "## Stage Summary",
        "",
    ]

    for item in summary.get("stage_status_summary") or []:
        lines.append(
            f"- {item.get('agent')}: last_status={item.get('last_status')} "
            f"(executed {item.get('count')}x)"
        )
    if not summary.get("stage_status_summary"):
        lines.append("- No stage history recorded.")

    lines.extend(
        [
            "",
            "## Sizing Snapshot",
            "",
        ]
    )
    for line in summary.get("sizing_summary") or ["n/a"]:
        lines.append(f"- {line}")

    lines.extend(
        [
            "",
            "## Verification",
            "",
            f"- Simulation intent: {summary.get('simulation_intent') or 'n/a'}",
            f"- Analyses run: {', '.join(summary.get('analyses') or []) or 'none'}",
        ]
    )
    if summary.get("simulation_skipped"):
        lines.append(f"- Simulation status: skipped ({summary.get('skip_reason') or 'reason not provided'})")
    else:
        lines.append("- Simulation status: completed")

    lines.extend(
        [
            "",
            "### Extracted Metrics",
            "",
        ]
    )
    metrics = summary.get("key_metrics") or {}
    if metrics:
        for key, value in metrics.items():
            lines.append(f"- {key}: {_fmt_value(value)}")
    else:
        lines.append("- No extracted metrics were recorded.")

    lines.extend(
        [
            "",
            "### Requirement Verdicts",
            "",
            "| Requirement | Requested | Measured | Status | Assessment |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    verdicts = summary.get("requirement_verdicts") or []
    if verdicts:
        for item in verdicts:
            lines.append(
                "| "
                f"{item.get('requirement') or 'n/a'} | "
                f"{_fmt_value(item.get('requested'))} | "
                f"{_fmt_value(item.get('measured'))} | "
                f"{item.get('status') or 'n/a'} | "
                f"{item.get('assessment') or 'n/a'} |"
            )
    else:
        lines.append("| none | n/a | n/a | n/a | n/a |")

    lines.extend(
        [
            "",
            "## Artifacts",
            "",
            f"- Artifact directory: {summary.get('artifact_dir') or 'n/a'}",
        ]
    )
    for path in summary.get("recommended_visuals") or []:
        lines.append(f"- Recommended visual: {path}")
    if not summary.get("recommended_visuals"):
        lines.append("- Recommended visual: none")

    return "\n".join(lines).rstrip() + "\n"


def render_showcase_rollup_markdown(*, mode: str, out_dir: str, case_summaries: list[dict]) -> str:
    lines = [
        "# TI Final Showcase Summary",
        "",
        f"- Primary command: `{FINAL_SHOWCASE_PRIMARY_COMMAND}`",
        f"- Backup command: `{FINAL_SHOWCASE_BACKUP_COMMAND}`",
        f"- Showcase mode: {mode}",
        f"- Output directory: {out_dir}",
        "",
        "## Selected Cases",
        "",
        "| Case | Role | Topology | Verdict | Verification | Recommended visual |",
        "| --- | --- | --- | --- | --- | --- |",
    ]

    for item in case_summaries:
        visuals = item.get("recommended_visuals") or []
        lines.append(
            "| "
            f"{item.get('case')} | "
            f"{item.get('showcase_role')} | "
            f"{item.get('selected_topology')} | "
            f"{item.get('overall_verdict')} | "
            f"{item.get('verification_status')} | "
            f"{visuals[0] if visuals else 'n/a'} |"
        )

    lines.extend(
        [
            "",
            "## Excluded Cases",
            "",
        ]
    )
    for item in FINAL_SHOWCASE_EXCLUDED_CASES:
        lines.append(f"- {item['case']}: {item['reason']}")

    return "\n".join(lines).rstrip() + "\n"


def stable_summary_index(*, mode: str, out_dir: str, case_summaries: list[dict]) -> dict:
    return {
        "mode": mode,
        "out_dir": out_dir,
        "primary_command": FINAL_SHOWCASE_PRIMARY_COMMAND,
        "backup_command": FINAL_SHOWCASE_BACKUP_COMMAND,
        "selected_cases": [item.get("case") for item in case_summaries],
        "case_summaries": case_summaries,
        "excluded_cases": FINAL_SHOWCASE_EXCLUDED_CASES,
    }


def dumps_pretty(payload: dict) -> str:
    return json.dumps(payload, indent=2, sort_keys=True)
