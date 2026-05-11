#!/usr/bin/env python3
import argparse
import contextlib
import csv
import html
import importlib.util
import json
import mimetypes
import os
import re
import shutil
import socket
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "i13-mplconfig"))
os.environ.setdefault("I13_SCHEMATIC_LCAPY_TIMEOUT", "3")

from core.demo_catalog import (
    READINESS_EXPERIMENTAL,
    READINESS_STABLE_DEMO,
    READINESS_STABLE_NO_SWEEP,
    get_demo_case,
    readiness_label,
    slugify_label,
)
from core.demo_safe import summarize_sizing
from core.reference_usage import summarize_reference_usage
from core.showcase_artifacts import (
    LATEST_ROOT,
    artifacts_for_row,
    load_showcase_manifest,
    organize_showcase_latest,
    reconstruct_rows_from_manifest,
    row_from_final_state,
    sweep_group_from_output,
)
from core.sweep_registry import (
    case_ui_category,
    default_sweep_parameter,
    get_case_sweep_schema,
    list_ui_cases,
)
from demo_showcase import run_sweep
from main import run_case


TITLE = "Multi-Agent LLM Analog Circuit Design Automation"

def _build_ui_catalog(
    include_experimental: bool = False,
    sponsor_demo_only: bool = True,
    include_advanced: bool = False,
):
    rows = list_ui_cases(include_experimental=include_experimental, sponsor_demo_only=sponsor_demo_only)
    if not sponsor_demo_only and not include_advanced:
        rows = [row for row in rows if row.get("readiness") == READINESS_STABLE_DEMO]
    case_options = {}
    params = {}
    categories = {}
    readiness = {}
    labels = {}
    for row in rows:
        key = row.get("key")
        if not key:
            continue
        schema = row.get("sweep_schema") or get_case_sweep_schema(key)
        sweep_params = schema.get("sweep_parameters") or {}
        if not sweep_params:
            continue
        case_options[key] = key
        categories[key] = row.get("category") or case_ui_category(key)
        readiness[key] = row.get("readiness", READINESS_EXPERIMENTAL)
        labels[key] = row.get("display_name", key)
        params[key] = {
            name: {
                "label": meta.get("label", name),
                "default": float(meta.get("default", 0.0)),
                "min": float(meta.get("min", 0.0)),
                "max": float(meta.get("max", 1.0)),
                "step": float(meta.get("step", 1.0)),
            }
            for name, meta in sweep_params.items()
        }
    return case_options, params, categories, readiness, labels


CASE_OPTIONS, PARAMS, CASE_CATEGORIES, CASE_READINESS, CASE_LABELS = _build_ui_catalog(
    include_experimental=False,
    sponsor_demo_only=True,
)


def _refresh_ui_catalog(include_experimental: bool = False, sponsor_demo_only: bool = True):
    global CASE_OPTIONS, PARAMS, CASE_CATEGORIES, CASE_READINESS, CASE_LABELS
    CASE_OPTIONS, PARAMS, CASE_CATEGORIES, CASE_READINESS, CASE_LABELS = _build_ui_catalog(
        include_experimental=include_experimental,
        sponsor_demo_only=sponsor_demo_only,
        include_advanced=include_experimental,
    )

BACKENDS = [
    "Offline deterministic",
    "Hugging Face netlist generator",
    "OpenAI fallback",
]

EXAMPLE_PROMPTS = [
    "Design a first-order RC low-pass filter with 1 kHz cutoff.",
    "Design an RLC bandpass filter centered at 10 kHz with Q of 2.",
    "Design a common-source amplifier with 20 dB gain, 1 MHz bandwidth, under 2 mW.",
    "Design a current mirror with 100 uA reference current and 2x mirror ratio.",
    "Design an op amp with high gain, MHz UGBW, and 2 pF load.",
]

ADDITIONAL_PROMPTS = [
    "Design a MOS source follower buffer for 5 pF load.",
]

AGENT_PIPELINE = [
    "TopologyAgent",
    "SizingAgent",
    "ConstraintAgent",
    "NetlistAgent",
    "OperatingPointAgent",
    "SimulationAgent",
    "RefinementAgent",
    "Artifact/Report Generator",
]

REGEN_COMMAND = "venv/bin/python3 demo_showcase.py --all-safe"


@contextlib.contextmanager
def backend_environment(backend: str):
    keys = ["USE_HF_NETLIST", "HF_SPACE_ID", "USE_OPENAI", "LLM_BACKEND"]
    previous = {key: os.environ.get(key) for key in keys}
    try:
        if backend == "Hugging Face netlist generator":
            os.environ["USE_HF_NETLIST"] = "1"
            os.environ.setdefault("HF_SPACE_ID", "potatoman869/spice_netlist-generator")
            os.environ["USE_OPENAI"] = "0"
            os.environ["LLM_BACKEND"] = "rule_based"
        elif backend == "OpenAI fallback":
            os.environ["USE_HF_NETLIST"] = "0"
            os.environ["USE_OPENAI"] = "1"
            os.environ["LLM_BACKEND"] = "openai"
        else:
            os.environ["USE_HF_NETLIST"] = "0"
            os.environ["USE_OPENAI"] = "0"
            os.environ["LLM_BACKEND"] = "rule_based"
        yield
    finally:
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def parse_design_prompt(prompt: str) -> dict:
    text = " ".join((prompt or "").strip().split())
    lowered = text.lower()
    selected_case, topology_hint, reason = _select_case_from_prompt(lowered)
    base_case = get_demo_case(CASE_OPTIONS[selected_case])
    constraints = dict(base_case.get("constraints") or {})

    gain = _extract_number_before(lowered, ["db", "decibel"])
    if gain is not None:
        constraints["target_gain_db"] = gain

    bandwidth = _extract_frequency_after_keywords(lowered, ["bandwidth", "bw", "ugbw", "unity-gain", "unity gain"])
    if bandwidth is not None:
        if selected_case == "folded_cascode_opamp" or "ugbw" in lowered or "unity" in lowered:
            constraints["target_ugbw_hz"] = bandwidth
        else:
            constraints["target_bw_hz"] = bandwidth

    cutoff = _extract_frequency_after_keywords(lowered, ["cutoff", "corner", "low-pass", "low pass", "filter", "near"])
    if cutoff is not None:
        constraints["target_fc_hz"] = cutoff

    center = _extract_frequency_after_keywords(lowered, ["centered", "center", "centre", "bandpass", "band-pass"])
    if center is not None:
        constraints["target_center_hz"] = center
        if selected_case == "rlc_bandpass":
            constraints.pop("target_fc_hz", None)

    q_value = _extract_q(lowered)
    if q_value is not None:
        constraints["quality_factor_q"] = q_value
        if selected_case == "rlc_bandpass" and constraints.get("target_center_hz"):
            constraints["target_bw_hz"] = float(constraints["target_center_hz"]) / max(float(q_value), 1e-12)

    power = _extract_value_with_units(lowered, ["mw", "milliwatt", "milliwatts"], scale=1.0)
    if power is not None:
        constraints["power_limit_mw"] = power

    load_cap = _extract_value_with_units(lowered, ["ff", "pf", "nf", "uf", "f"], unit_scales={"ff": 1e-15, "pf": 1e-12, "nf": 1e-9, "uf": 1e-6, "f": 1.0})
    if load_cap is not None:
        if selected_case in {"rc", "rlc_bandpass"} and ("capacitor" in lowered or "capacitance" in lowered or " cap" in lowered):
            constraints["fixed_cap_f"] = load_cap
        else:
            constraints["load_cap_f"] = load_cap

    ref_current = _extract_value_with_units(
        lowered,
        ["ua", "microamp", "microamps", "ma", "milliamp", "amps", "amp", "a"],
        unit_scales={"ua": 1e-6, "microamp": 1e-6, "microamps": 1e-6, "ma": 1e-3, "milliamp": 1e-3, "amps": 1.0, "amp": 1.0, "a": 1.0},
    )
    ratio = _extract_ratio(lowered)
    if ref_current is not None:
        if selected_case == "mirror" and ("reference current" in lowered or "bias current" in lowered):
            constraints["reference_current_a"] = ref_current
            constraints["target_iout_a"] = ref_current * float(ratio or constraints.get("mirror_ratio") or 1.0)
        else:
            constraints["target_iout_a"] = ref_current
    if ratio is not None:
        constraints["mirror_ratio"] = ratio
        if selected_case == "mirror" and constraints.get("reference_current_a") is not None:
            constraints["target_iout_a"] = float(constraints["reference_current_a"]) * float(ratio)

    supply = _extract_supply(lowered)
    if supply is not None:
        constraints["supply_v"] = supply

    requested_function = _requested_function_label(selected_case, lowered)
    parsed = {
        "prompt": text,
        "requested_circuit_function": requested_function,
        "topology_hint": topology_hint,
        "selected_case": selected_case,
        "selected_demo_case": CASE_OPTIONS[selected_case],
        "selected_topology": base_case.get("forced_topology"),
        "why_topology": reason,
        "constraints": constraints,
    }
    return parsed


def _select_case_from_prompt(lowered: str) -> tuple[str, str, str]:
    if any(token in lowered for token in ("rlc", "bandpass", "band-pass")):
        return (
            "rlc_bandpass",
            "second-order RLC band-pass",
            "The prompt asks for an RLC/band-pass frequency-selective circuit, so the stable RLC band-pass case is used.",
        )
    if any(token in lowered for token in ("folded", "cascode op", "op-amp", "op amp", "opamp", "operational amplifier", "ota")):
        return (
            "folded_cascode_opamp",
            "folded-cascode op amp",
            "The prompt asks for an op-amp/high-gain MHz block, so the closest stable showcase case is the folded-cascode op-amp.",
        )
    if "common-source" in lowered or "common source" in lowered or ("amplifier" in lowered and "buffer" not in lowered):
        return (
            "common_source",
            "common-source amplifier",
            "The prompt asks for voltage gain with bandwidth/power constraints, matching the common-source gain block.",
        )
    if any(token in lowered for token in ("source follower", "common drain", "buffer")):
        if "mos_buffer" in CASE_OPTIONS:
            return (
                "mos_buffer",
                "MOS source follower buffer",
                "The prompt emphasizes buffering/load drive, so the source-follower MOS buffer case is used.",
            )
        return (
            "common_source",
            "common-source gain stage (buffer path hidden in sponsor mode)",
            "The strict sponsor-mode UI currently exposes only verified-sweep cases; source-follower buffer remains outside the default set.",
        )
    if "mirror" in lowered or "reference current" in lowered:
        return (
            "mirror",
            "current mirror",
            "The prompt names a mirror/reference-current function, mapping directly to the current mirror case.",
        )
    if "comparator" in lowered or "decision" in lowered:
        return (
            "comparator",
            "regenerative comparator",
            "The prompt asks for a decision circuit, so the comparator transient case is the closest stable example.",
        )
    if any(token in lowered for token in ("low-pass", "low pass", "filter", "cutoff", "corner")):
        return (
            "rc",
            "first-order RC low-pass",
            "The prompt asks for a cutoff/filter function, so the first-order RC low-pass is the stable supported case.",
        )
    return (
        "rc",
        "inferred RC low-pass",
        "No specialized topology keyword was found; the UI defaults to the most reliable first-order RC design path.",
    )


def _requested_function_label(case_key: str, lowered: str) -> str:
    labels = {
        "rc": "low-pass filtering",
        "rlc_bandpass": "RLC band-pass filtering",
        "common_source": "voltage gain amplification",
        "mos_buffer": "source-follower buffering",
        "mirror": "current reference/mirroring",
        "folded_cascode_opamp": "high-gain op-amp design",
        "comparator": "transient decision/comparison",
        "bandgap_reference": "precision reference generation",
    }
    if "high gain" in lowered:
        return f"{labels.get(case_key, case_key)} with high gain"
    return labels.get(case_key, case_key)


def _extract_number_before(text: str, unit_tokens: list[str]):
    for unit in unit_tokens:
        match = re.search(rf"([-+]?\d+(?:\.\d+)?)\s*{re.escape(unit)}\b", text)
        if match:
            return float(match.group(1))
    return None


def _extract_frequency_after_keywords(text: str, keywords: list[str]):
    matches = list(re.finditer(r"([-+]?\d+(?:\.\d+)?)\s*(ghz|mhz|khz|hz)\b", text))
    if not matches:
        return None
    scales = {"ghz": 1e9, "mhz": 1e6, "khz": 1e3, "hz": 1.0}
    for match in matches:
        window = text[max(0, match.start() - 42): match.end() + 42]
        if any(keyword in window for keyword in keywords):
            return float(match.group(1)) * scales[match.group(2)]
    return None


def _extract_value_with_units(text: str, units: list[str], scale: float = None, unit_scales: dict = None):
    unit_scales = unit_scales or {unit: scale for unit in units}
    ordered = sorted(units, key=len, reverse=True)
    for unit in ordered:
        pattern = rf"([-+]?\d+(?:\.\d+)?)\s*{re.escape(unit)}\b"
        match = re.search(pattern, text)
        if match:
            return float(match.group(1)) * float(unit_scales.get(unit, 1.0))
    return None


def _extract_ratio(text: str):
    match = re.search(r"([-+]?\d+(?:\.\d+)?)\s*x\b", text)
    if match:
        return float(match.group(1))
    match = re.search(r"ratio\s*(?:of|=|:)?\s*([-+]?\d+(?:\.\d+)?)", text)
    if match:
        return float(match.group(1))
    return None


def _extract_q(text: str):
    for pattern in (
        r"\bq\s*(?:of|=|:)?\s*([-+]?\d+(?:\.\d+)?)\b",
        r"quality\s*factor\s*(?:of|=|:)?\s*([-+]?\d+(?:\.\d+)?)\b",
    ):
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def _extract_supply(text: str):
    for pattern in (
        r"(?:supply|vdd|vcc)\s*(?:of|=|:)?\s*([-+]?\d+(?:\.\d+)?)\s*v\b",
        r"([-+]?\d+(?:\.\d+)?)\s*v\s*(?:supply|vdd|vcc)\b",
    ):
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def normalize_constraints(case_key: str, values: dict) -> dict:
    if case_key == "mirror":
        ref_current = float(values.get("reference_current_a", PARAMS[case_key]["reference_current_a"]["default"]))
        ratio = float(values.get("mirror_ratio", PARAMS[case_key]["mirror_ratio"]["default"]))
        return {
            "reference_current_a": ref_current,
            "mirror_ratio": ratio,
            "target_iout_a": ref_current * ratio,
        }
    constraints = {}
    for key, value in values.items():
        normalized_key = key
        if case_key == "rlc_bandpass" and key == "quality_factor_q":
            center = float(values.get("target_center_hz", PARAMS[case_key]["target_center_hz"]["default"]))
            constraints["quality_factor_q"] = float(value)
            constraints["target_bw_hz"] = center / max(float(value), 1e-12)
            continue
        constraints[normalized_key] = float(value)
    return constraints


def run_design(case_key: str, values: dict, backend: str, prompt_context: dict = None) -> dict:
    resolved_case = CASE_OPTIONS[case_key]
    constraints = normalize_constraints(case_key, values)
    base_case = get_demo_case(resolved_case)
    spec_bits = ", ".join(f"{key}={value:g}" for key, value in constraints.items())
    prompt_text = (prompt_context or {}).get("prompt")
    spec_prefix = prompt_text or base_case.get("specification")
    override = {
        "specification": f"{spec_prefix} Live UI override: {spec_bits}.",
        "constraints": constraints,
        "artifact_label": f"ui_{case_key}_{slugify_label(spec_bits)}",
    }
    with backend_environment(backend):
        final_state = run_case(resolved_case, case_override=override)
    row = row_from_final_state(case_key, final_state)
    prior_rows, prior_groups = _prior_showcase_state(exclude_case=case_key)
    manifest = organize_showcase_latest(
        command="venv/bin/python3 ui_showcase.py",
        case_rows=prior_rows + [row],
        sweep_groups=prior_groups,
        architecture_summary=(
            "This live demo combines agentic topology and sizing decisions, optional LLM netlist generation, "
            "and deterministic SPICE validation. Hugging Face and OpenAI backends are opportunistic; "
            "the deterministic template path is the guaranteed offline fallback."
        ),
        clean=True,
    )
    result = _result_from_state(case_key, final_state, manifest)
    if prompt_context:
        result["prompt_context"] = prompt_context
    return result


def run_prompt_design(prompt: str, backend: str) -> dict:
    parsed = parse_design_prompt(prompt)
    values = _ui_values_from_constraints(parsed["selected_case"], parsed["constraints"])
    return run_design(parsed["selected_case"], values, backend, prompt_context=parsed)


def _ui_values_from_constraints(case_key: str, constraints: dict) -> dict:
    values = {}
    for key, meta in PARAMS[case_key].items():
        if case_key == "mirror" and key == "reference_current_a":
            values[key] = float(
                constraints.get(
                    "reference_current_a",
                    constraints.get("target_iout_a", meta["default"]),
                )
            )
            continue
        if case_key == "rlc_bandpass" and key == "quality_factor_q":
            if constraints.get("quality_factor_q") is not None:
                values[key] = float(constraints["quality_factor_q"])
            elif constraints.get("target_center_hz") and constraints.get("target_bw_hz"):
                values[key] = float(constraints["target_center_hz"]) / max(float(constraints["target_bw_hz"]), 1e-12)
            else:
                values[key] = float(meta["default"])
            continue
        values[key] = float(constraints.get(key, meta["default"]))
    return values


def run_ui_sweep(case_key: str, sweep_param: str, center_value: float, backend: str, values: list[float] = None) -> dict:
    resolved_case = CASE_OPTIONS[case_key]
    actual_param = sweep_param
    values = values or sorted({center_value * 0.5, center_value, center_value * 2.0})
    output_dir = Path("artifacts/showcase_runs/_latest_working") / f"ui_{case_key}_{actual_param}"
    with backend_environment(backend):
        rows, root = run_sweep(
            resolved_case,
            actual_param,
            values,
            output_dir=str(output_dir),
            update_latest=False,
        )
    new_group = sweep_group_from_output(f"{case_key}_{actual_param}", str(root), rows)
    prior_rows, prior_groups = _prior_showcase_state(exclude_sweep=new_group.get("name"))
    manifest = organize_showcase_latest(
        command="venv/bin/python3 ui_showcase.py --sweep",
        case_rows=prior_rows,
        sweep_groups=prior_groups + [new_group],
        architecture_summary=(
            "The sweep regenerates sizing, netlist, schematic, plots, metrics, and final reports at each parameter value. "
            "External LLM backends are used only when configured and valid; deterministic artifacts remain the fallback."
        ),
        clean=True,
    )
    row_artifacts = [
        artifacts_for_row(manifest, row.get("case"), row.get("sweep_parameter"), row.get("requested_spec"))
        for row in rows
    ]
    return {
        "kind": "sweep",
        "case": case_key,
        "sweep_param": sweep_param,
        "rows": rows,
        "row_artifacts": row_artifacts,
        "manifest": manifest,
        "artifacts": _latest_artifacts(),
        "summary_path": str(LATEST_ROOT / "summary.md"),
    }


def _prior_showcase_state(exclude_case: str = None, exclude_sweep: str = None) -> tuple[list[dict], list[dict]]:
    manifest_path = LATEST_ROOT / "artifact_manifest.json"
    rows, groups = reconstruct_rows_from_manifest(manifest_path)
    case_targets = set()
    if exclude_case:
        case_targets.add(exclude_case)
        case_targets.add(CASE_OPTIONS.get(exclude_case, exclude_case))
    if case_targets:
        rows = [row for row in rows if row.get("case") not in case_targets]
    if exclude_sweep:
        groups = [group for group in groups if group.get("name") != exclude_sweep]
    return rows, groups


def _result_from_state(case_key: str, final_state: dict, manifest: dict) -> dict:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    backend = sim.get("netlist_backend_metadata") or final_state.get("netlist_backend_metadata") or {}
    reference_usage = summarize_reference_usage(final_state)
    schematic_status = sim.get("schematic_status") or ""
    current_artifacts = artifacts_for_row(manifest, case_key)
    canonical_netlist = _first_existing(current_artifacts.get("netlist")) or sim.get("saved_netlist_path")
    canonical_report = _first_existing(current_artifacts.get("report")) or (
        str(Path(sim.get("artifact_dir") or ".") / "final_report.txt") if sim.get("artifact_dir") else ""
    )
    evidence = _artifact_evidence(case_key, sim, current_artifacts, canonical_netlist, canonical_report)
    raw_verdict = verification.get("overall_verdict") or verification.get("final_status") or final_state.get("status") or "n/a"
    verdict = raw_verdict
    if evidence.get("status") != "ok" and str(raw_verdict).lower() in {"fully_verified", "pass", "passed"}:
        verdict = "artifact_incomplete"
    result = {
        "kind": "design",
        "case": case_key,
        "specification": final_state.get("specification") or "",
        "topology": final_state.get("selected_topology") or "n/a",
        "topology_reasoning": final_state.get("topology_reasoning") or "",
        "agents_used": AGENT_PIPELINE,
        "pipeline_summary": _pipeline_summary(final_state),
        "constraints": final_state.get("constraints") or {},
        "component_values": summarize_sizing(final_state.get("sizing") or {}),
        "backend_used": backend.get("backend_used") or "n/a",
        "fallback_reason": backend.get("fallback_reason") or "",
        "backend_provenance": _backend_provenance(final_state),
        "verdict": verdict,
        "metrics": verification.get("extracted_metrics") or {},
        "requirements": verification.get("requirement_evaluations") or [],
        "reference_usage": reference_usage,
        "netlist_preview": _read_preview(canonical_netlist),
        "schematic_status": schematic_status,
        "schematic_failure_reason": sim.get("schematic_failure_reason") or "",
        "final_state": final_state,
        "raw_paths": {
            "generated_sp": sim.get("saved_netlist_path") or "",
            "schematic": sim.get("schematic_png_path") or sim.get("schematic_svg_path") or "",
            "schematic_png": sim.get("schematic_png_path") or "",
            "schematic_svg": sim.get("schematic_svg_path") or "",
            "ac_plot": sim.get("ac_plot") or "",
            "dc_plot": sim.get("dc_plot") or "",
            "tran_plot": sim.get("tran_plot") or "",
            "final_report": canonical_report,
        },
        "manifest": manifest,
        "artifacts": current_artifacts,
        "all_artifacts": _latest_artifacts(),
        "artifact_debug": {
            "canonical_root": str(LATEST_ROOT),
            "manifest_artifact_count": len((manifest or {}).get("artifacts") or []),
            "case_label": case_key,
            "evidence_status": evidence.get("status"),
            "missing_artifacts": evidence.get("missing", []),
        },
        "summary_path": str(LATEST_ROOT / "summary.md"),
    }
    result["metrics_display"] = normalize_metrics_for_display(result, parsed_constraints=final_state.get("constraints") or {})
    return result


def _artifact_evidence(case_key: str, sim: dict, artifacts: dict, canonical_netlist: str, canonical_report: str) -> dict:
    schema = get_case_sweep_schema(case_key)
    missing = []
    if not canonical_netlist or not Path(str(canonical_netlist)).exists():
        missing.append("generated.sp")
    if not canonical_report or not Path(str(canonical_report)).exists():
        missing.append("final_report.txt")
    schematic = _first_existing(artifacts.get("schematic")) or sim.get("schematic_png_path") or sim.get("schematic_svg_path")
    if not schematic or not Path(str(schematic)).exists():
        missing.append("schematic")
    required_any = schema.get("required_any_plots") or []
    if required_any:
        has_plot = False
        mapping = {"tran_plot": "transient_plot"}
        for key in required_any:
            lookup = mapping.get(key, key)
            path = _first_existing(artifacts.get(lookup))
            if not path:
                raw_key = "tran_plot" if lookup == "transient_plot" else lookup
                raw = sim.get(raw_key)
                if raw and Path(str(raw)).exists():
                    path = raw
            if path:
                has_plot = True
                break
        if not has_plot:
            missing.append("plot")
    return {"status": "ok" if not missing else "missing_artifacts", "missing": missing}


def _first_existing(paths):
    for path in paths or []:
        if path and Path(path).exists():
            return path
    return None


def _pipeline_summary(final_state: dict) -> list[dict]:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or final_state.get("verification_summary") or {}
    backend = sim.get("netlist_backend_metadata") or final_state.get("netlist_backend_metadata") or {}
    return [
        {
            "stage": "Specification parsing",
            "input": "natural-language request",
            "output": f"{len(final_state.get('constraints') or {})} normalized constraints",
            "status": "complete" if final_state.get("constraints") else "partial",
        },
        {
            "stage": "Topology selection",
            "input": "specification + constraints + references",
            "output": final_state.get("selected_topology") or "n/a",
            "status": final_state.get("status") or "n/a",
        },
        {
            "stage": "Sizing",
            "input": "selected topology + target specs",
            "output": "; ".join(summarize_sizing(final_state.get("sizing") or {})[:3]) or "n/a",
            "status": "complete" if final_state.get("sizing") else "missing",
        },
        {
            "stage": "Netlist generation",
            "input": "sizing + template/LLM backend",
            "output": backend.get("backend_used") or final_state.get("netlist_source") or "n/a",
            "status": "complete" if sim.get("saved_netlist_path") else "missing",
        },
        {
            "stage": "Simulation",
            "input": "generated.sp",
            "output": ", ".join(sim.get("analyses") or []) or "n/a",
            "status": "skipped" if sim.get("simulation_skipped") else ("complete" if sim.get("returncode") == 0 else "not complete"),
        },
        {
            "stage": "Metrics extraction",
            "input": "ngspice CSV/log artifacts",
            "output": ", ".join(sorted((verification.get("extracted_metrics") or {}).keys())[:6]) or "n/a",
            "status": "complete" if verification.get("extracted_metrics") else "partial",
        },
        {
            "stage": "Verification",
            "input": "measured metrics + requested specs",
            "output": verification.get("overall_verdict") or verification.get("final_status") or "n/a",
            "status": verification.get("final_status") or "n/a",
        },
        {
            "stage": "Refinement suggestion",
            "input": "verification failures/limitations",
            "output": "; ".join((final_state.get("refinement_report") or {}).get("notes") or [])[:180] or "n/a",
            "status": (final_state.get("refinement_report") or {}).get("next_action") or "n/a",
        },
        {
            "stage": "Report/artifacts",
            "input": "final design state",
            "output": sim.get("artifact_dir") or "n/a",
            "status": "complete" if sim.get("artifact_dir") else "missing",
        },
    ]


def _backend_provenance(final_state: dict) -> dict:
    sim = final_state.get("simulation_results") or {}
    backend = sim.get("netlist_backend_metadata") or final_state.get("netlist_backend_metadata") or {}
    llm_resolution = final_state.get("llm_resolution") or {}
    usage = summarize_reference_usage(final_state)
    llm_calls = [
        (item.get("data") or {}).get("task") or (item.get("data") or {}).get("agent")
        for item in final_state.get("history") or []
        if item.get("event") == "llm_call"
    ]
    return {
        "backend_used": backend.get("backend_used") or "n/a",
        "llm_backend_configured": llm_resolution.get("configured_backend") or "n/a",
        "llm_backend_resolved": llm_resolution.get("resolved_backend") or "n/a",
        "llm_used_for": [item for item in llm_calls if item] or ["none; deterministic fallback"],
        "deterministic_equations_used": usage.get("equations_used") or [],
        "templates_used": usage.get("templates_used") or [],
        "simulator_used": sim.get("ngspice_path") or "ngspice unavailable",
        "simulator_status": "skipped" if sim.get("simulation_skipped") else ("complete" if sim.get("returncode") == 0 else "not complete"),
        "fallback_reason": backend.get("fallback_reason") or "",
    }


_METRIC_DISPLAY_KEYS = (
    "gain_db",
    "bandwidth_hz",
    "ugbw_hz",
    "phase_margin_deg",
    "power_mw",
    "fc_hz",
    "center_freq_hz",
    "q_factor",
    "reference_current_a",
    "output_current_a",
    "mirror_ratio_requested",
    "mirror_ratio_measured",
    "ratio_error_percent",
    "load_cap_f",
)


def normalize_metrics_for_display(source, parsed_constraints: dict = None) -> dict:
    """Pull a stable, presentation-ready metric dict from many likely locations.

    Accepts either a final_state-like dict (from run_case) or the result dict from
    _result_from_state. Always returns a dict with the documented keys; missing
    measurements are returned as None so the UI can still render the slot.
    """
    if isinstance(source, dict) and "final_state" in source:
        final_state = source.get("final_state") or {}
        result_metrics = source.get("metrics") or {}
        constraints_default = source.get("constraints") or {}
    else:
        final_state = source if isinstance(source, dict) else {}
        result_metrics = {}
        constraints_default = {}

    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    extracted = verification.get("extracted_metrics") or {}
    sizing = final_state.get("sizing") or {}
    constraints = parsed_constraints or final_state.get("constraints") or constraints_default or {}
    topology = final_state.get("selected_topology") or ""

    candidates = [extracted, sim, result_metrics, sizing, constraints]

    out = {key: None for key in _METRIC_DISPLAY_KEYS}

    def first_value(*keys):
        for key in keys:
            for source_dict in candidates:
                value = (source_dict or {}).get(key)
                if value is None:
                    continue
                try:
                    return float(value)
                except (TypeError, ValueError):
                    return value
        return None

    out["gain_db"] = first_value("gain_db", "transient_gain_db", "peak_gain_db")
    if topology in {"rc_lowpass", "rlc_lowpass_2nd_order", "rlc_highpass_2nd_order", "rlc_bandpass_2nd_order"}:
        out["gain_db"] = first_value("peak_gain_db") if topology == "rlc_bandpass_2nd_order" else None
    out["bandwidth_hz"] = first_value("bandwidth_hz")
    out["ugbw_hz"] = first_value("ugbw_hz")
    out["phase_margin_deg"] = first_value("phase_margin_deg")
    out["power_mw"] = first_value("power_mw")
    out["fc_hz"] = first_value("fc_hz", "cutoff_hz")
    out["center_freq_hz"] = first_value("center_freq_hz", "center_hz", "peak_freq_hz", "peak_frequency_hz")
    out["q_factor"] = first_value("q_factor", "quality_factor_q")
    out["reference_current_a"] = first_value("reference_current_a")
    out["output_current_a"] = first_value("output_current_a", "iout_a")
    out["mirror_ratio_requested"] = first_value("mirror_ratio_requested", "mirror_ratio")
    out["mirror_ratio_measured"] = first_value("mirror_ratio_measured")
    out["ratio_error_percent"] = first_value("ratio_error_percent")
    out["load_cap_f"] = first_value("load_cap_f")

    if (
        out["mirror_ratio_measured"] is None
        and out["reference_current_a"] not in (None, 0)
        and out["output_current_a"] is not None
    ):
        try:
            out["mirror_ratio_measured"] = float(out["output_current_a"]) / float(out["reference_current_a"])
        except (TypeError, ZeroDivisionError):
            out["mirror_ratio_measured"] = None
    if (
        out["ratio_error_percent"] is None
        and out["mirror_ratio_requested"] not in (None, 0)
        and out["mirror_ratio_measured"] is not None
    ):
        try:
            requested = float(out["mirror_ratio_requested"])
            measured = float(out["mirror_ratio_measured"])
            if requested:
                out["ratio_error_percent"] = 100.0 * abs(measured - requested) / abs(requested)
        except (TypeError, ZeroDivisionError):
            pass

    if out["q_factor"] is None and out["center_freq_hz"] and out["bandwidth_hz"]:
        try:
            bw = float(out["bandwidth_hz"])
            if bw > 0:
                out["q_factor"] = float(out["center_freq_hz"]) / bw
        except (TypeError, ZeroDivisionError):
            pass

    return out


def _latest_artifacts() -> dict:
    data = load_showcase_manifest(LATEST_ROOT / "artifact_manifest.json")
    out = {}
    for item in data.get("artifacts") or []:
        path = item.get("showcase_copy_path")
        if path and Path(path).exists():
            out.setdefault(item.get("type"), []).append(path)
    return out


def _read_preview(path: str, limit: int = 5000) -> str:
    if not path or not Path(path).exists():
        return ""
    text = Path(path).read_text(errors="replace")
    return text[:limit]


def smoke_test() -> int:
    result = run_design(
        "rc",
        {"target_fc_hz": 1234.0, "fixed_cap_f": 10e-9},
        "Offline deterministic",
    )
    ok = bool(result.get("netlist_preview")) and (LATEST_ROOT / "summary.md").exists()
    print("UI smoke test PASS" if ok else "UI smoke test FAIL: expected artifacts were not generated")
    print(f"Summary: {LATEST_ROOT / 'summary.md'}")
    return 0


def streamlit_app():
    import streamlit as st

    st.set_page_config(page_title=TITLE, layout="wide")

    sponsor_mode = st.sidebar.toggle("Sponsor Demo Mode", value=True)
    show_advanced_cases = False if sponsor_mode else st.sidebar.toggle(
        "Show Advanced Cases", value=False, help="Reveal stable_no_sweep and experimental cases."
    )
    include_experimental = bool(show_advanced_cases and not sponsor_mode)
    _refresh_ui_catalog(include_experimental=include_experimental, sponsor_demo_only=sponsor_mode)
    if show_advanced_cases:
        st.sidebar.warning(
            f"{readiness_label(READINESS_STABLE_NO_SWEEP)} and {readiness_label(READINESS_EXPERIMENTAL)} "
            "cases may produce partial verification or missing artifacts."
        )

    category_options = sorted(set(CASE_CATEGORIES.values()))
    selected_categories = st.sidebar.multiselect(
        "Case Categories",
        category_options,
        default=category_options,
    )
    st.session_state["selected_categories"] = selected_categories

    backend_rows = [
        ("Deterministic/Native", "available"),
        ("OpenAI", "configured" if (os.getenv("OPENAI_API_KEY") or "").strip() else "not configured"),
        ("HuggingFace", "configured" if (os.getenv("HF_TOKEN") or "").strip() else "not configured"),
        ("ngspice", "available" if shutil.which("ngspice") else "unavailable"),
    ]
    st.sidebar.markdown("**Backend Status**")
    for name, status in backend_rows:
        st.sidebar.caption(f"{name}: {status}")

    st.title(TITLE)
    st.caption(
        "Natural-language prompt -> topology selection -> sizing -> SPICE netlist -> ngspice simulation "
        "-> schematic -> verified report. Main artifacts collect under artifacts/showcase_runs/latest/."
    )

    tabs = st.tabs(
        [
            "Natural Language Design",
            "Live Parameter Sweep",
            "Showcase Gallery",
            "Artifact Browser",
            "Analog Designer View",
            "System Architecture",
        ]
    )

    with tabs[0]:
        render_natural_language_tab(st)

    with tabs[1]:
        render_sweep_tab(st)

    with tabs[2]:
        render_gallery_tab(st)

    with tabs[3]:
        render_artifact_browser_tab(st)

    with tabs[4]:
        render_analog_designer_tab(st)

    with tabs[5]:
        render_architecture_tab(st)


def render_natural_language_tab(st):
    left, right = st.columns([0.35, 0.65])
    with left:
        st.subheader("Prompt")
        default_prompt = st.session_state.get("design_prompt", EXAMPLE_PROMPTS[1])
        prompt = st.text_area("Enter analog design request", value=default_prompt, height=116)
        st.session_state["design_prompt"] = prompt
        st.caption("Recommended Live Demo Prompts")
        for idx, example in enumerate(EXAMPLE_PROMPTS):
            if st.button(example, key=f"example_prompt_{idx}", use_container_width=True):
                st.session_state["design_prompt"] = example
                st.rerun()
        with st.expander("Additional prompt"):
            for idx, example in enumerate(ADDITIONAL_PROMPTS):
                if st.button(example, key=f"additional_prompt_{idx}", use_container_width=True):
                    st.session_state["design_prompt"] = example
                    st.rerun()
        backend = st.selectbox("Backend", BACKENDS, key="nl_backend")
        run_clicked = st.button("Run Design", type="primary", use_container_width=True, key="nl_run")
    if run_clicked:
        with st.spinner("Parsing prompt, choosing topology, sizing, simulating, and collecting artifacts..."):
            st.session_state["latest_result"] = run_prompt_design(prompt, backend)
    with right:
        render_streamlit_result(st.session_state.get("latest_result"), show_prompt=True)


def render_sweep_tab(st):
    left, right = st.columns([0.34, 0.66])
    with left:
        st.subheader("Live Parameter Sweep")
        selected_categories = st.session_state.get("selected_categories") or []
        case_keys = [
            key
            for key in CASE_OPTIONS.keys()
            if (not selected_categories) or (CASE_CATEGORIES.get(key) in selected_categories)
        ]
        if not case_keys:
            st.warning("No cases match the selected category filter.")
            return
        case_key = st.selectbox(
            "Circuit case",
            case_keys,
            format_func=lambda key: f"{CASE_LABELS.get(key, key)} ({key})",
        )
        st.caption(
            f"{CASE_CATEGORIES.get(case_key, 'Mixed-Signal Extras')} | "
            f"{readiness_label(CASE_READINESS.get(case_key, READINESS_EXPERIMENTAL))}"
        )
        backend = st.selectbox("Backend", BACKENDS)
        values = {}
        for key, meta in PARAMS[case_key].items():
            values[key] = st.number_input(
                meta["label"],
                min_value=float(meta["min"]),
                max_value=float(meta["max"]),
                value=float(meta["default"]),
                step=float(meta["step"]),
                format="%.8g",
            )
        default_param = default_sweep_parameter(CASE_OPTIONS[case_key]) or next(iter(PARAMS[case_key].keys()))
        params = list(PARAMS[case_key].keys())
        sweep_param = st.selectbox(
            "Sweep parameter",
            params,
            index=max(0, params.index(default_param)) if default_param in params else 0,
        )
        raw_values = st.text_input(
            "Sweep values",
            value=_default_sweep_values(values[sweep_param]),
            help="Comma-separated numeric values. Scientific notation is OK.",
        )
        design_clicked = st.button("Run single case", type="secondary", use_container_width=True)
        sweep_clicked = st.button("Run sweep", type="primary", use_container_width=True)

    if design_clicked:
        with st.spinner("Running design flow..."):
            st.session_state["latest_result"] = run_design(case_key, values, backend)
    if sweep_clicked:
        with st.spinner("Running parameter sweep..."):
            parsed_values = _parse_csv_floats(raw_values) or [float(values[sweep_param])]
            st.session_state["latest_result"] = run_ui_sweep(case_key, sweep_param, float(values[sweep_param]), backend, values=parsed_values)
    with right:
        render_streamlit_result(st.session_state.get("latest_result"))


def render_gallery_tab(st):
    st.subheader("Showcase Gallery")
    st.caption("Gallery cards are populated from the latest generated artifacts. Run `bash run_final_showcase.sh full` for the richest set.")
    groups = _artifact_groups()
    desired = [
        ("RC low-pass cutoff sweep", ["rc"]),
        ("RLC bandpass frequency response", ["rlc_bandpass"]),
        ("Common-source gain block", ["common_source"]),
        ("Current mirror DC behavior", ["mirror"]),
        ("Folded-cascode/op-amp example", ["folded_cascode_opamp"]),
        ("Comparator transient decision", ["comparator", "static_comparator"]),
        ("Bandgap reference behavior", ["bandgap_reference"]),
    ]
    cols = st.columns(2)
    for idx, (title, tokens) in enumerate(desired):
        group = _find_group(groups, tokens)
        with cols[idx % 2]:
            render_gallery_card(st, title, group)


def render_artifact_browser_tab(st):
    st.subheader("Artifact Browser")
    st.caption("These links point at the copied presentation artifacts under artifacts/showcase_runs/latest/.")
    manifest_path = LATEST_ROOT / "artifact_manifest.json"
    if not manifest_path.exists():
        st.info(f"No latest manifest yet. Run a natural-language design, sweep, or `{REGEN_COMMAND}`.")
        return
    st.markdown(f"[Open static index]({LATEST_ROOT / 'index.html'}) | [summary.md]({LATEST_ROOT / 'summary.md'}) | [artifact_manifest.json]({manifest_path})")
    data = load_showcase_manifest(manifest_path)
    artifacts = data.get("artifacts") or []
    tabs = st.tabs(["Summary", "Netlist", "Plots", "Schematic", "Metrics", "Verification Report", "Manifest"])

    def _render_paths(paths, preview=True):
        if not paths:
            st.info("No artifacts found for this tab.")
            return
        for path in paths:
            st.markdown(f"- `{path}`")
            suffix = Path(path).suffix.lower()
            if suffix in {".png", ".jpg", ".jpeg", ".svg"}:
                _render_image_or_warning(st, path, Path(path).name)
                continue
            if preview and suffix in {".txt", ".md", ".json", ".sp", ".csv"}:
                with st.expander(f"Preview {Path(path).name}", expanded=False):
                    st.code(_read_preview(str(path), limit=4000), language=_language_for_path(Path(path)))

    with tabs[0]:
        summary_path = LATEST_ROOT / "summary.md"
        if summary_path.exists():
            st.code(_read_preview(str(summary_path), limit=14000), language="markdown")
        else:
            st.info("summary.md not generated yet.")
    with tabs[1]:
        _render_paths([item.get("showcase_copy_path") for item in artifacts if item.get("type") == "netlist"])
    with tabs[2]:
        _render_paths(
            [
                item.get("showcase_copy_path")
                for item in artifacts
                if item.get("type") in {"ac_plot", "dc_plot", "transient_plot", "comparison_plot"}
            ],
            preview=False,
        )
    with tabs[3]:
        _render_paths([item.get("showcase_copy_path") for item in artifacts if item.get("type") == "schematic"], preview=False)
    with tabs[4]:
        _render_paths([item.get("showcase_copy_path") for item in artifacts if item.get("type") == "metrics"])
    with tabs[5]:
        _render_paths([item.get("showcase_copy_path") for item in artifacts if item.get("type") == "report"])
    with tabs[6]:
        st.dataframe(artifacts, use_container_width=True)
        st.json(data)


ANALOG_DESIGNER_NOTES = {
    "rc": "First-order anti-alias or bandwidth-limiting stage for sensor/ADC front ends.",
    "rlc_bandpass": "Narrowband selection stage for tuned signal-conditioning paths.",
    "common_source": "Single-stage voltage-gain block in analog front-end chains.",
    "mirror": "Bias-current replication and branch-current distribution block.",
    "folded_cascode_opamp": "High-gain core for precision amplification and loop control.",
    "comparator": "Decision block for threshold detection and conversion interfaces.",
    "bandgap_reference": "Reference generator used by bias and data-converter subsystems.",
}


def render_analog_designer_tab(st):
    st.subheader("Analog Designer View")
    selected_categories = st.session_state.get("selected_categories") or []
    visible = [
        key for key in CASE_OPTIONS.keys() if (not selected_categories) or (CASE_CATEGORIES.get(key) in selected_categories)
    ]
    for case_key in visible:
        case_meta = get_demo_case(CASE_OPTIONS[case_key])
        schema = get_case_sweep_schema(CASE_OPTIONS[case_key])
        param_meta = (schema.get("sweep_parameters") or {}).get(default_sweep_parameter(CASE_OPTIONS[case_key]) or "", {})
        with st.expander(f"{CASE_LABELS.get(case_key, case_key)} ({case_key})", expanded=False):
            st.caption(
                f"{CASE_CATEGORIES.get(case_key, 'Mixed-Signal Extras')} | "
                f"{readiness_label(CASE_READINESS.get(case_key, READINESS_EXPERIMENTAL))}"
            )
            st.write(ANALOG_DESIGNER_NOTES.get(case_key, "General-purpose analog block demonstration path."))
            st.write(case_meta.get("specification", "n/a"))
            st.markdown("**Default sweep parameter:**")
            st.write(f"`{default_sweep_parameter(CASE_OPTIONS[case_key]) or 'n/a'}`")
            st.markdown("**Default sweep points:**")
            st.write((param_meta.get("default_points") or [])[:5])
            st.markdown("**Core checks:**")
            st.write((param_meta.get("requirement_keys") or [])[:8] or ["verification_summary.final_status"])


def render_architecture_tab(st):
    st.subheader("System Architecture")
    st.markdown(
        """
Specification / Prompt -> TopologyAgent -> SizingAgent -> ConstraintAgent -> NetlistAgent -> OperatingPointAgent -> SimulationAgent -> RefinementAgent -> Artifact/Report Generator

LLMs are used for interpretation, topology reasoning, netlist generation, and refinement suggestions when configured. Deterministic tools handle design equations, ngspice simulation, metric extraction, pass/fail checks, plots, reports, and presentation artifact collection.

Fallbacks preserve reliability when cloud tools, quotas, Lcapy, LaTeX, or optional packages are unavailable. The demo never reports `PASSED` unless simulation-backed checks pass.
"""
    )
    st.code("\n".join(f"{idx + 1}. {name}" for idx, name in enumerate(AGENT_PIPELINE)))
    st.markdown(
        """
Reference knowledge sources used by the agents include `design_equations.json`, `device_selection_heuristics.json`, `cookbook_circuits.json`, and `template_library.json`. Each run records the concrete reference IDs in the final report and metrics summary.
"""
    )


def render_streamlit_result(result: dict | None, show_prompt: bool = False):
    import streamlit as st

    if not result:
        st.info("Enter a prompt or run a sweep to populate live artifacts.")
        return
    if result.get("kind") == "sweep":
        st.subheader(f"Sweep: {result['case']} / {result['sweep_param']}")
        rows = result.get("rows") or []
        st.dataframe(rows, use_container_width=True)
        for path in result.get("artifacts", {}).get("comparison_plot", []):
            _render_image_or_warning(st, path, "Comparison plot")
        st.subheader("Per-Run Evidence")
        row_artifacts = result.get("row_artifacts") or [{} for _ in rows]
        for idx, row in enumerate(rows):
            artifacts = row_artifacts[idx] if idx < len(row_artifacts) else {}
            netlist = _first_existing(artifacts.get("netlist")) or row.get("generated_netlist")
            schematic = _first_existing(artifacts.get("schematic")) or row.get("schematic_png")
            report = _first_existing(artifacts.get("report")) or row.get("final_report")
            st.markdown(
                f"- `{row.get('sweep_parameter')}={row.get('requested_spec')}`: "
                f"components `{row.get('component_values') or 'n/a'}`; measured "
                f"`{row.get('measured_metric') or 'metric'}={row.get('measured_result') or 'n/a'}`; "
                f"verdict `{row.get('pass_fail')}`; "
                f"netlist `{netlist or 'missing'}` | schematic `{schematic or 'missing'}` | report `{report or 'missing'}`"
            )
            if not netlist or not Path(str(netlist)).exists():
                _missing_artifact(st, "sweep netlist")
        st.markdown(f"[summary.md]({result['summary_path']})")
        with st.expander("Artifact Manifest / Debug", expanded=False):
            st.json(result.get("manifest") or {})
        return

    if show_prompt and result.get("prompt_context"):
        ctx = result["prompt_context"]
        with st.expander("Parsed Design Request", expanded=True):
            parsed_cols = st.columns(3)
            parsed_cols[0].metric("Function", ctx.get("requested_circuit_function", "n/a"))
            parsed_cols[1].metric("Topology Hint", ctx.get("topology_hint", "n/a"))
            parsed_cols[2].metric("Mapped Case", ctx.get("selected_demo_case", "n/a"))
            st.write(ctx.get("why_topology"))
            st.json(ctx.get("constraints") or {})

    if result.get("specification"):
        with st.expander("Natural-Language Prompt / Spec", expanded=True):
            st.write(result.get("specification"))
            st.json(result.get("constraints") or {})

    top = st.columns(4)
    top[0].metric("Topology", result.get("topology", "n/a"))
    top[1].metric("Backend", result.get("backend_used", "n/a"))
    top[2].metric("Verdict", result.get("verdict", "n/a"))
    top[3].metric("Case", result.get("case", "n/a"))
    if result.get("fallback_reason"):
        st.caption(result["fallback_reason"])
    schematic_status = result.get("schematic_status") or "n/a"
    if schematic_status:
        st.caption(f"Schematic status: `{schematic_status}`" + (
            f" — {result.get('schematic_failure_reason')}" if result.get("schematic_failure_reason") else ""
        ))
    st.subheader("Agent-by-Agent Pipeline")
    pipeline = result.get("pipeline_summary") or []
    if pipeline:
        st.dataframe(pipeline, use_container_width=True)
    else:
        st.write(" -> ".join(result.get("agents_used") or AGENT_PIPELINE))
    with st.expander("Backend Provenance", expanded=True):
        st.json(result.get("backend_provenance") or {})
    usage = result.get("reference_usage") or {}
    with st.expander("Reference Knowledge Used", expanded=True):
        st.write(
            {
                "equations_used": usage.get("equations_used") or [],
                "templates_used": usage.get("templates_used") or [],
                "heuristics_used": usage.get("heuristics_used") or [],
                "cookbook_entries_used": _cookbook_entries(usage),
            }
        )
    st.subheader("Generated Component Values")
    st.write(result.get("component_values") or ["n/a"])
    st.subheader("Evaluated Metrics")
    metrics_display = result.get("metrics_display") or normalize_metrics_for_display(result)
    _render_metrics_grid(st, metrics_display)
    with st.expander("All extracted metrics (raw)", expanded=False):
        st.json(result.get("metrics") or {})
    if result.get("requirements"):
        st.subheader("Verification Checks")
        st.dataframe(result["requirements"], use_container_width=True)
    st.subheader("generated.sp")
    if result.get("netlist_preview"):
        st.code(result.get("netlist_preview"), language="spice")
    else:
        _missing_artifact(st, "generated.sp")
    image_cols = st.columns(3)
    for idx, artifact_type in enumerate(("schematic", "ac_plot", "dc_plot", "transient_plot")):
        paths = result.get("artifacts", {}).get(artifact_type, [])[:1]
        if not paths and artifact_type in {"ac_plot", "dc_plot", "transient_plot"}:
            continue
        for path in paths:
            with image_cols[idx % 3]:
                _render_image_or_warning(st, path, artifact_type)
    if not any(result.get("artifacts", {}).get(key) for key in ("ac_plot", "dc_plot", "transient_plot")):
        _missing_artifact(st, "simulation plot")
    links = []
    for label, path in (
        ("final_report.txt", (result.get("artifacts", {}).get("report") or [""])[0]),
        ("summary.md", result.get("summary_path")),
    ):
        if path:
            links.append(f"`{label}: {path}`")
    st.markdown(" | ".join(links))
    report_path = _first_existing(result.get("artifacts", {}).get("report")) or result.get("raw_paths", {}).get("final_report")
    with st.expander("Report Content", expanded=True):
        if report_path and Path(str(report_path)).exists():
            st.text(_read_preview(str(report_path), limit=12000))
        else:
            _missing_artifact(st, "final_report.txt")
    with st.expander("Artifact Manifest / Debug", expanded=False):
        st.json(
            {
                "current_result_artifacts": result.get("artifacts") or {},
                "raw_paths": result.get("raw_paths") or {},
                "artifact_debug": result.get("artifact_debug") or {},
                "manifest": result.get("manifest") or {},
            }
        )


_METRIC_DISPLAY_ORDER = (
    ("gain_db", "Gain", "dB", "{value:.2f}"),
    ("bandwidth_hz", "Bandwidth", "Hz", "{value:.4g}"),
    ("ugbw_hz", "UGBW", "Hz", "{value:.4g}"),
    ("phase_margin_deg", "Phase margin", "deg", "{value:.1f}"),
    ("power_mw", "Power", "mW", "{value:.4g}"),
    ("fc_hz", "Cutoff fc", "Hz", "{value:.4g}"),
    ("center_freq_hz", "Centre freq", "Hz", "{value:.4g}"),
    ("q_factor", "Q factor", "", "{value:.3g}"),
    ("reference_current_a", "Iref", "A", "{value:.4g}"),
    ("output_current_a", "Iout", "A", "{value:.4g}"),
    ("mirror_ratio_requested", "Ratio (req)", "", "{value:.3g}"),
    ("mirror_ratio_measured", "Ratio (meas)", "", "{value:.3g}"),
    ("ratio_error_percent", "Ratio err", "%", "{value:.3g}"),
    ("load_cap_f", "Load cap", "F", "{value:.4g}"),
)


def _format_metric_value(value, fmt: str, suffix: str = "") -> str:
    if value is None:
        return "n/a"
    try:
        text = fmt.format(value=float(value))
    except (TypeError, ValueError):
        return str(value)
    if suffix:
        return f"{text} {suffix}"
    return text


def _render_metrics_grid(st, metrics_display: dict) -> None:
    if not metrics_display:
        st.info("No metrics extracted yet — run a design.")
        return
    visible = [(key, label, suffix, fmt) for key, label, suffix, fmt in _METRIC_DISPLAY_ORDER if metrics_display.get(key) is not None]
    if not visible:
        st.warning("Simulation completed but no normalized metrics were extracted.")
        return
    cols = st.columns(min(4, max(1, len(visible))))
    for idx, (key, label, suffix, fmt) in enumerate(visible):
        cols[idx % len(cols)].metric(label, _format_metric_value(metrics_display.get(key), fmt, suffix))


def _missing_artifact(st, label: str) -> None:
    st.warning(
        f"{label} is not available in `{LATEST_ROOT}`. "
        f"Regenerate the canonical showcase bundle with `{REGEN_COMMAND}`."
    )


def _render_image_or_warning(st, path: str, caption: str) -> None:
    if not path or not Path(str(path)).exists():
        _missing_artifact(st, caption)
        return
    suffix = Path(str(path)).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".svg"}:
        st.info(f"{caption} exists at `{path}`, but it is not an image file.")
        return
    try:
        st.image(str(path), caption=caption)
    except Exception as exc:
        st.warning(f"Could not render {caption} from `{path}`: {exc}")


def _language_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".json":
        return "json"
    if suffix in {".sp", ".cir"}:
        return "spice"
    if suffix in {".md", ".txt"}:
        return "markdown" if suffix == ".md" else "text"
    if suffix == ".csv":
        return "csv"
    return "text"


def _default_sweep_values(center: float) -> str:
    values = sorted({float(center) * 0.5, float(center), float(center) * 2.0})
    return ",".join(f"{value:.6g}" for value in values)


def _parse_csv_floats(raw: str) -> list[float]:
    values = []
    for item in (raw or "").split(","):
        item = item.strip()
        if not item:
            continue
        try:
            values.append(float(item))
        except ValueError:
            continue
    return values


def _cookbook_entries(usage: dict) -> list[str]:
    ids = usage.get("reference_ids_used") or []
    return [item for item in ids if "cookbook" in item.lower() or "circuit" in item.lower()]


def _artifact_groups() -> dict:
    manifest_path = LATEST_ROOT / "artifact_manifest.json"
    if not manifest_path.exists():
        return {}
    manifest = load_showcase_manifest(manifest_path)
    groups = {}
    for item in manifest.get("artifacts") or []:
        path = item.get("showcase_copy_path")
        if path and not Path(path).exists():
            continue
        case_name = item.get("case_name") or "case"
        value = item.get("parameter_sweep_value")
        key = case_name if value in (None, "") else f"{case_name}_{item.get('parameter_sweep_name')}_{value}"
        group = groups.setdefault(
            key,
            {
                "case": case_name,
                "spec": item.get("parameter_sweep_name") or case_name,
                "topology": case_name,
                "verdict": item.get("final_verdict") or "",
                "backend": item.get("backend_used") or "",
                "paths": {},
            },
        )
        group["paths"].setdefault(item.get("type"), []).append(item.get("showcase_copy_path"))
        if item.get("final_verdict"):
            group["verdict"] = item["final_verdict"]
        if item.get("backend_used"):
            group["backend"] = item["backend_used"]
    return groups


def _find_group(groups: dict, tokens: list[str]) -> dict | None:
    for key, group in groups.items():
        haystack = f"{key} {group.get('case')}".lower()
        if any(token.lower() in haystack for token in tokens):
            return group
    return None


def render_gallery_card(st, title: str, group: dict | None):
    with st.container():
        st.markdown(f"**{title}**")
        if not group:
            st.info("No artifact yet. Run the full showcase to populate this example.")
            return
        st.caption(f"Request/spec: {group.get('spec') or group.get('case')}")
        case_key = group.get("case")
        if case_key in CASE_READINESS:
            st.caption(
                f"{CASE_CATEGORIES.get(case_key, 'Mixed-Signal Extras')} | "
                f"{readiness_label(CASE_READINESS.get(case_key, READINESS_EXPERIMENTAL))}"
            )
        st.write(f"Selected topology: `{group.get('topology') or group.get('case')}`")
        paths = group.get("paths") or {}
        thumbs = []
        for artifact_type in ("schematic", "ac_plot", "dc_plot", "transient_plot", "comparison_plot"):
            for path in paths.get(artifact_type) or []:
                if Path(path).exists() and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}:
                    thumbs.append((artifact_type, path))
                    break
        img_cols = st.columns(2)
        for idx, (artifact_type, path) in enumerate(thumbs[:2]):
            with img_cols[idx]:
                _render_image_or_warning(st, path, artifact_type)
        st.write(f"Verdict: `{group.get('verdict') or 'n/a'}`")
        links = []
        for artifact_type, label in (("netlist", "generated.sp"), ("report", "final_report.txt"), ("comparison_table", "comparison table")):
            for path in paths.get(artifact_type) or []:
                links.append(f"[{label}]({path})")
                break
        if links:
            st.markdown(" | ".join(links))


def gradio_app(port: int):
    import gradio as gr

    def run_action(case_key, backend, sweep_param, action, *param_values):
        active_params = list(PARAMS[case_key].keys())
        values = {key: float(param_values[idx]) for idx, key in enumerate(active_params)}
        if action == "Run Sweep":
            result = run_ui_sweep(case_key, sweep_param, values[sweep_param], backend)
        else:
            result = run_design(case_key, values, backend)
        return result_to_markdown(result), result.get("netlist_preview", ""), _first_image(result, "schematic"), _first_image(result, "ac_plot"), _first_image(result, "transient_plot")

    with gr.Blocks(title=TITLE, css="footer{display:none}") as demo:
        gr.Markdown(f"# {TITLE}")
        default_case = next(iter(CASE_OPTIONS.keys()))
        default_param = next(iter(PARAMS[default_case].keys()))
        with gr.Row():
            case = gr.Dropdown(list(CASE_OPTIONS.keys()), value=default_case, label="Circuit case")
            backend = gr.Dropdown(BACKENDS, value=BACKENDS[0], label="Backend")
            sweep_param = gr.Dropdown(list(PARAMS[default_case].keys()), value=default_param, label="Sweep parameter")
            action = gr.Radio(["Run Design", "Run Sweep"], value="Run Design", label="Action")
        inputs = []
        for key, meta in PARAMS[default_case].items():
            inputs.append(gr.Number(value=meta["default"], label=key, visible=True))
        out_md = gr.Markdown()
        out_netlist = gr.Code(language="spice", label="generated.sp")
        with gr.Row():
            schematic = gr.Image(label="Schematic")
            ac_plot = gr.Image(label="AC/DC plot")
            tran_plot = gr.Image(label="Transient plot")
        run_btn = gr.Button("Run")
        run_btn.click(run_action, [case, backend, sweep_param, action] + inputs, [out_md, out_netlist, schematic, ac_plot, tran_plot])
    demo.launch(server_name="127.0.0.1", server_port=port)


def result_to_markdown(result: dict | None) -> str:
    if not result:
        return ""
    if result.get("kind") == "sweep":
        rows = result.get("rows") or []
        lines = [
            f"## Sweep: {result.get('case')} / {result.get('sweep_param')}",
            "",
            "| requested | measured | verdict | backend |",
            "|---:|---:|---|---|",
        ]
        for row in rows:
            lines.append(f"| {row.get('requested_spec')} | {row.get('measured_result')} | {row.get('pass_fail')} | {row.get('backend_used') or 'n/a'} |")
        lines.append(f"\n[summary.md]({result.get('summary_path')})")
        return "\n".join(lines)
    metrics_display = result.get("metrics_display") or normalize_metrics_for_display(result)
    metric_lines = "\n".join(
        f"- {label}: {_format_metric_value(metrics_display.get(key), fmt, suffix)}"
        for key, label, suffix, fmt in _METRIC_DISPLAY_ORDER
        if metrics_display.get(key) is not None
    ) or "- n/a"
    raw_metrics = json.dumps(result.get("metrics") or {}, indent=2, sort_keys=True)
    components = "\n".join(f"- {item}" for item in result.get("component_values") or ["n/a"])
    return (
        f"## {result.get('case')}\n\n"
        f"- Topology: `{result.get('topology')}`\n"
        f"- Backend: `{result.get('backend_used')}`\n"
        f"- Verdict: `{result.get('verdict')}`\n"
        f"- Schematic: `{result.get('schematic_status') or 'n/a'}`\n"
        f"- final_report.txt: `{(result.get('artifacts', {}).get('report') or ['n/a'])[0]}`\n"
        f"- summary.md: `{result.get('summary_path')}`\n\n"
        f"### Evaluated Metrics\n{metric_lines}\n\n"
        f"### Component Values\n{components}\n\n"
        f"### Raw Metrics\n```json\n{raw_metrics}\n```"
    )


def _first_image(result: dict, artifact_type: str):
    for path in result.get("artifacts", {}).get(artifact_type, []):
        if Path(path).exists() and Path(path).suffix.lower() in {".png", ".jpg", ".jpeg"}:
            return path
    return None


def fallback_server(port: int):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/artifacts/"):
                return self._serve_static(Path(self.path.lstrip("/")))
            self._send_html(render_fallback_page())

        def do_POST(self):
            length = int(self.headers.get("Content-Length", "0"))
            payload = parse_qs(self.rfile.read(length).decode("utf-8"))
            case_key = payload.get("case", [next(iter(CASE_OPTIONS.keys()))])[0]
            backend = payload.get("backend", [BACKENDS[0]])[0]
            action = payload.get("action", ["Run Design"])[0]
            values = {}
            for key, meta in PARAMS[case_key].items():
                values[key] = float(payload.get(key, [meta["default"]])[0])
            try:
                if action == "Run Sweep":
                    sweep_param = payload.get("sweep_param", [next(iter(PARAMS[case_key]))])[0]
                    result = run_ui_sweep(case_key, sweep_param, values[sweep_param], backend)
                else:
                    result = run_design(case_key, values, backend)
                self._send_html(render_fallback_page(result=result, selected=case_key, backend=backend, values=values))
            except Exception as exc:
                self._send_html(render_fallback_page(error=str(exc), selected=case_key, backend=backend, values=values))

        def _serve_static(self, path: Path):
            if not path.exists() or not path.is_file():
                self.send_error(404)
                return
            self.send_response(200)
            self.send_header("Content-Type", mimetypes.guess_type(path)[0] or "application/octet-stream")
            self.end_headers()
            self.wfile.write(path.read_bytes())

        def _send_html(self, text: str):
            data = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, fmt, *args):
            print("[ui]", fmt % args)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"OPEN UI:\nhttp://localhost:{port}")
    server.serve_forever()


def render_fallback_page(result=None, error="", selected=None, backend=BACKENDS[0], values=None) -> str:
    selected = selected or next(iter(CASE_OPTIONS.keys()))
    values = values or {key: meta["default"] for key, meta in PARAMS[selected].items()}
    case_options = "".join(f"<option value='{key}' {'selected' if key == selected else ''}>{key}</option>" for key in CASE_OPTIONS)
    backend_options = "".join(f"<option {'selected' if item == backend else ''}>{item}</option>" for item in BACKENDS)
    inputs = []
    for key, meta in PARAMS[selected].items():
        inputs.append(
            f"<label>{html.escape(meta['label'])}<input name='{key}' type='number' step='any' value='{values.get(key, meta['default']):.8g}'></label>"
        )
    sweep_options = "".join(f"<option value='{key}'>{key}</option>" for key in PARAMS[selected])
    result_html = render_result_html(result) if result else ""
    error_html = f"<div class='error'>{html.escape(error)}</div>" if error else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>{TITLE}</title>
<style>
:root {{ color-scheme: light; --ink:#172033; --muted:#657089; --line:#d9dee8; --ok:#087f5b; --bad:#b42318; --panel:#ffffff; --bg:#f5f7fb; --accent:#1f6feb; }}
body {{ margin:0; font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif; background:var(--bg); color:var(--ink); }}
header {{ padding:28px 34px 18px; background:#111827; color:white; }}
h1 {{ margin:0 0 8px; font-size:30px; letter-spacing:0; }}
main {{ display:grid; grid-template-columns:minmax(280px,360px) 1fr; gap:22px; padding:24px 34px; }}
section,.panel {{ background:var(--panel); border:1px solid var(--line); border-radius:8px; padding:18px; }}
label {{ display:block; font-size:13px; color:var(--muted); margin:12px 0 6px; }}
input,select {{ width:100%; box-sizing:border-box; border:1px solid var(--line); border-radius:6px; padding:9px 10px; font-size:14px; }}
button {{ border:0; border-radius:6px; padding:10px 14px; font-weight:650; cursor:pointer; }}
.primary {{ background:var(--accent); color:white; width:100%; margin-top:14px; }}
.secondary {{ background:#e8eef9; color:#17345f; width:100%; margin-top:10px; }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(230px,1fr)); gap:14px; }}
.metric {{ border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfcff; }}
.metric b {{ display:block; font-size:12px; color:var(--muted); margin-bottom:4px; }}
pre {{ overflow:auto; max-height:420px; background:#101828; color:#ecfdf5; padding:14px; border-radius:8px; }}
img {{ max-width:100%; border:1px solid var(--line); border-radius:8px; background:white; }}
a {{ color:#1456b8; }}
.error {{ color:var(--bad); background:#fff0f0; border:1px solid #ffd1d1; border-radius:8px; padding:12px; margin-bottom:12px; }}
table {{ border-collapse:collapse; width:100%; font-size:13px; }} td,th {{ border:1px solid var(--line); padding:7px; text-align:left; }}
@media (max-width:850px) {{ main {{ grid-template-columns:1fr; padding:16px; }} header {{ padding:22px 18px; }} }}
</style></head>
<body><header><h1>{TITLE}</h1><div>Live parameter edits regenerate netlists, schematics, plots, metrics, and reports in <code>artifacts/showcase_runs/latest/</code>.</div></header>
<main><section><form method="post">
<label>Circuit case<select name="case" onchange="this.form.submit()">{case_options}</select></label>
<label>Backend<select name="backend">{backend_options}</select></label>
{''.join(inputs)}
<label>Sweep parameter<select name="sweep_param">{sweep_options}</select></label>
<button class="primary" name="action" value="Run Design">Run Design</button>
<button class="secondary" name="action" value="Run Sweep">Run Sweep</button>
</form></section><section>{error_html}{result_html or '<div class="panel">Run a design or sweep to populate the live artifacts.</div>'}</section></main></body></html>"""


def render_result_html(result: dict) -> str:
    if result.get("kind") == "sweep":
        rows = result.get("rows") or []
        body = "".join(
            f"<tr><td>{html.escape(str(row.get('requested_spec')))}</td><td>{html.escape(str(row.get('measured_result')))}</td><td>{html.escape(str(row.get('pass_fail')))}</td><td>{html.escape(str(row.get('backend_used') or 'n/a'))}</td></tr>"
            for row in rows
        )
        plot = _img_tag((result.get("artifacts", {}).get("comparison_plot") or [""])[0])
        return f"<h2>Sweep: {html.escape(result.get('case',''))}</h2><table><tr><th>requested</th><th>measured</th><th>verdict</th><th>backend</th></tr>{body}</table>{plot}<p><a href='/{result.get('summary_path')}'>summary.md</a></p>"
    metrics_display = result.get("metrics_display") or normalize_metrics_for_display(result)
    metric_cards = "".join(
        f"<div class='metric'><b>{html.escape(label)}</b>{html.escape(_format_metric_value(metrics_display.get(key), fmt, suffix))}</div>"
        for key, label, suffix, fmt in _METRIC_DISPLAY_ORDER
        if metrics_display.get(key) is not None
    )
    raw_metrics_json = html.escape(json.dumps(result.get("metrics") or {}, indent=2, sort_keys=True))
    components = "".join(f"<li>{html.escape(str(item))}</li>" for item in result.get("component_values") or ["n/a"])
    artifacts = result.get("artifacts", {})
    schematic_status = result.get("schematic_status") or "n/a"
    return f"""
<div class="grid">
<div class="metric"><b>Chosen topology</b>{html.escape(result.get('topology','n/a'))}</div>
<div class="metric"><b>Backend used</b>{html.escape(result.get('backend_used','n/a'))}</div>
<div class="metric"><b>Pass/fail verdict</b>{html.escape(result.get('verdict','n/a'))}</div>
<div class="metric"><b>Schematic</b>{html.escape(schematic_status)}</div>
</div>
<h3>Evaluated Metrics</h3>
<div class="grid">{metric_cards or '<div class="metric"><b>n/a</b>No metrics extracted.</div>'}</div>
<h3>Generated Component Values</h3><ul>{components}</ul>
<details><summary>Raw extracted metrics</summary><pre>{raw_metrics_json}</pre></details>
<h3>generated.sp</h3><pre>{html.escape(result.get('netlist_preview') or 'n/a')}</pre>
<div class="grid">{_img_tag((artifacts.get('schematic') or [''])[0])}{_img_tag((artifacts.get('ac_plot') or artifacts.get('dc_plot') or [''])[0])}{_img_tag((artifacts.get('transient_plot') or [''])[0])}</div>
<p><a href="/{(artifacts.get('report') or [''])[0]}">final_report.txt</a> | <a href="/{result.get('summary_path')}">summary.md</a></p>
"""


def _img_tag(path: str) -> str:
    if not path or not Path(path).exists():
        return ""
    return f"<img src='/{html.escape(path)}' alt='{html.escape(Path(path).name)}'>"


def choose_port(port: int) -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if sock.connect_ex(("127.0.0.1", port)) != 0:
            return port
    for candidate in range(port + 1, port + 50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            if sock.connect_ex(("127.0.0.1", candidate)) != 0:
                return candidate
    return port


def running_under_streamlit() -> bool:
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx

        return get_script_run_ctx() is not None
    except Exception:
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Launch the local live showcase UI.")
    parser.add_argument("--port", type=int, default=int(os.getenv("DEMO_UI_PORT", "8501")))
    parser.add_argument("--smoke-test", action="store_true")
    args = parser.parse_args()
    if args.smoke_test:
        return smoke_test()

    port = choose_port(args.port)
    if (
        importlib.util.find_spec("streamlit") is not None
        and os.getenv("I13_STREAMLIT_APP") != "1"
        and not running_under_streamlit()
    ):
        os.environ["I13_STREAMLIT_APP"] = "1"
        os.execv(
            sys.executable,
            [sys.executable, "-m", "streamlit", "run", __file__, "--server.address", "127.0.0.1", "--server.port", str(port)],
        )
    if importlib.util.find_spec("streamlit") is not None:
        streamlit_app()
        return 0
    if importlib.util.find_spec("gradio") is not None:
        print(f"OPEN UI:\nhttp://localhost:{port}")
        gradio_app(port)
        return 0
    fallback_server(port)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
