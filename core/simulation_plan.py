from copy import deepcopy

from core.topology_library import TOPOLOGY_LIBRARY


STANDARD_ANALYSIS_ORDER = ("op", "dc", "ac", "tran", "noise")

ANALYSIS_METADATA = {
    "op": {
        "title": "Operating Point",
        "description": "Verify the DC bias point before trusting small-signal or transient behavior.",
        "expected_artifacts": ["ngspice.log"],
    },
    "dc": {
        "title": "DC Sweep",
        "description": "Sweep a bias or supply variable to inspect compliance, common-mode range, or output swing.",
        "expected_artifacts": ["dc_out.csv", "dc_plot.svg"],
    },
    "ac": {
        "title": "AC Response",
        "description": "Measure small-signal gain, bandwidth, UGBW, and stability-related frequency metrics.",
        "expected_artifacts": ["ac_out.csv", "ac_plot.svg"],
    },
    "tran": {
        "title": "Transient",
        "description": "Check startup, large-signal response, settling, slew, and output swing in time domain.",
        "expected_artifacts": ["tran_in.csv", "tran_out.csv", "tran_plot.svg"],
    },
    "noise": {
        "title": "Noise",
        "description": "Estimate input-referred or output-referred noise when the topology is noise-sensitive.",
        "expected_artifacts": ["ngspice.log"],
    },
}

NOISE_RELEVANT_TOPOLOGIES = {
    "transimpedance_frontend",
    "two_stage_miller",
    "folded_cascode_opamp",
    "folded_cascode_opamp_core",
    "telescopic_cascode_opamp_core",
    "ldo_error_amp_core",
    "bandgap_reference_core",
}


def build_simulation_plan(topology: str, constraints: dict | None = None, override: dict | None = None) -> dict:
    constraints = dict(constraints or {})
    override = dict(override or {})
    topology_meta = deepcopy((TOPOLOGY_LIBRARY.get(topology) or {}).get("simulation_plan") or {})

    plan = deepcopy(topology_meta)
    plan.update(override)

    enabled_analyses = list(plan.get("analyses") or [])
    enabled_set = {item for item in enabled_analyses if item in STANDARD_ANALYSIS_ORDER}

    noise_relevant = (
        "noise" in enabled_set
        or bool(constraints.get("low_noise_priority"))
        or topology in NOISE_RELEVANT_TOPOLOGIES
    )

    analysis_catalog = []
    for name in STANDARD_ANALYSIS_ORDER:
        meta = ANALYSIS_METADATA[name]
        analysis_catalog.append(
            {
                "name": name,
                "title": meta["title"],
                "description": meta["description"],
                "enabled": name in enabled_set,
                "relevant": (name in enabled_set) or (name == "noise" and noise_relevant),
                "expected_artifacts": list(meta["expected_artifacts"]),
            }
        )

    hooks = deepcopy(plan.get("hooks") or {})
    param_sweep = deepcopy(plan.get("param_sweep") or hooks.get("param_sweep") or {})
    corner_sweep = deepcopy(plan.get("corner_sweep") or hooks.get("corner_sweep") or {})

    plan["topology"] = topology
    plan["analyses"] = enabled_analyses
    plan["analysis_catalog"] = analysis_catalog
    plan["analysis_sequence"] = [item for item in analysis_catalog if item["enabled"]]
    plan["hooks"] = {
        "param_sweep": {
            "available": True,
            "configured": bool(param_sweep),
            "definition": param_sweep,
            "status": "hook_only",
        },
        "corner_sweep": {
            "available": True,
            "configured": bool(corner_sweep),
            "definition": corner_sweep,
            "status": "hook_only",
        },
    }
    plan.setdefault("primary_metrics", [])
    plan.setdefault("required_constraint_targets", [])
    return plan
