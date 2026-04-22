from typing import Dict, List


DEMO_SAFE_CASES = [
    "rc",
    "wide_swing_mirror",
    "diff_pair_active_load",
    "opamp",
    "bandgap_reference",
    "static_comparator",
]


SPEC_KEYS = [
    "gain_db",
    "bandwidth_hz",
    "ugbw_hz",
    "fc_hz",
    "center_hz",
    "q_factor",
    "power_mw",
    "iout_a",
    "vref_v",
    "oscillation_hz",
    "decision_delay_s",
    "write_ok",
]


def summarize_sizing(sizing: Dict, max_items: int = 8) -> List[str]:
    if not isinstance(sizing, dict) or not sizing:
        return ["n/a"]

    if isinstance(sizing.get("stages"), list):
        lines = []
        for stage in sizing.get("stages", [])[:3]:
            name = stage.get("name", "stage")
            topo = stage.get("topology", "unknown")
            stage_sizing = stage.get("sizing") or {}
            keys = [key for key, value in stage_sizing.items() if isinstance(value, (int, float))][:3]
            snippet = ", ".join(f"{key}={stage_sizing[key]:.4g}" for key in keys)
            lines.append(f"{name} ({topo}): {snippet if snippet else 'numeric sizing unavailable'}")
        if not lines:
            lines.append("composite sizing present but no stage details were found")
        return lines

    numeric_keys = [
        key for key, value in sizing.items() if isinstance(value, (int, float))
    ]
    numeric_keys.sort()
    selected = numeric_keys[:max_items]
    if not selected:
        return ["no numeric sizing entries"]
    return [f"{key}={sizing[key]:.4g}" for key in selected]


def summarize_netlist(netlist: str, max_lines: int = 14) -> List[str]:
    if not netlist:
        return ["n/a"]
    lines = [line.rstrip() for line in str(netlist).splitlines() if line.strip()]
    if not lines:
        return ["n/a"]
    preview = lines[:max_lines]
    if len(lines) > max_lines:
        preview.append(f"... ({len(lines) - max_lines} more lines)")
    return preview


def extract_specs(sim: Dict) -> Dict:
    specs = {}
    if not isinstance(sim, dict):
        return specs
    for key in SPEC_KEYS:
        if sim.get(key) is not None:
            specs[key] = sim.get(key)
    return specs


def pass_fail_reasons(sim: Dict) -> List[str]:
    verification = (sim or {}).get("verification_summary") or {}
    reasons = []

    for group_name in ("target_checks", "analytical_checks"):
        for item in verification.get(group_name, []) or []:
            if item.get("status") != "fail":
                continue
            name = item.get("name", "unnamed_check")
            measured = item.get("measured")
            target = item.get("target")
            reasons.append(f"{group_name}:{name} measured={measured} target={target}")
            for issue in item.get("issues") or []:
                reasons.append(f"{group_name}:{name} issue={issue}")

    if (sim or {}).get("simulation_skipped"):
        reasons.append((sim or {}).get("skip_reason") or "Simulation skipped")

    if not reasons:
        passes = verification.get("passes")
        fails = verification.get("fails")
        unknown = verification.get("unknown")
        if passes is not None or fails is not None or unknown is not None:
            reasons.append(f"verification summary: {passes} pass / {fails} fail / {unknown} unknown")
        else:
            reasons.append("no verification checks were produced")

    return reasons
