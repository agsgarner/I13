# LLM Customized for Analog Circuit Design

## Overview

This repository is a multi-agent analog design demo flow. It takes a circuit goal, selects a topology, sizes a first-pass implementation, validates constraints, generates an ngspice netlist, runs simulation, and stores artifacts for presentation.

The framework is designed for capstone-style demos where we want traceability and repeatable outputs more than full custom-IC signoff accuracy.

## Flow

`Specification -> TopologyAgent -> SizingAgent -> ConstraintAgent -> NetlistAgent -> SimulationAgent -> RefinementAgent`

Each agent reads and writes shared memory so the full design state stays inspectable.

New in this version:
- `TopologyAgent` now supports LLM-assisted stage planning with a topology-preserving `topology_plan`.
- `TopologyAgent` now accepts per-stage constraint payloads via `constraints.stage_constraints`.
- The flow supports `composite_pipeline` designs that cascade multiple topology blocks.
- `NetlistAgent` now emits stage markers and validates stage-count/order continuity for cascaded netlists.
- Core op-amp, gm-stage, and comparator templates now use transistor-level first-pass netlists instead of behavioral placeholders.
- `RefinementAgent` can use LLM guidance to suggest bounded numeric sizing updates when deterministic refinement stalls.

## Repository Structure

- `agents/` - design agents and orchestration logic
- `core/` - shared defaults, memory helpers, topology library, demo case catalog
- `flow/` - lightweight workflow engine
- `flow/design_flow.py` - orchestration graph, retry logic, and refinement loop transitions
- `llm/` - OpenAI-backed and local stub LLM adapters
- `main.py` - run one demo case
- `demo_runner.py` - run a batch of demo cases
- `evaluation/benchmark_runner.py` - pass@k-oriented benchmark harness for report-ready evaluation

## Running

Run the default case:

```bash
python3 main.py
```

List available demo cases:

```bash
DESIGN_CASE=list python3 main.py
DESIGN_CASE=profiles python3 main.py
```

Run a specific case:

```bash
DESIGN_CASE=mirror python3 main.py
DESIGN_CASE=opamp python3 main.py
DESIGN_CASE=diff_pair python3 main.py
SHOW_HISTORY=1 DESIGN_CASE=mirror python3 main.py
```

Run a batch demo:

```bash
DEMO_LIMIT=4 python3 demo_runner.py
DESIGN_CASES=mirror,opamp,common_source,diff_pair python3 demo_runner.py
DEMO_PROFILE=ti_safe python3 demo_runner.py
STABLE_ONLY=1 python3 demo_runner.py
DEMO_PROFILE=list python3 demo_runner.py
```

Run a TI demo preflight before a presentation:

```bash
DESIGN_CASE=preflight DEMO_PROFILE=ti_safe python3 main.py
```

## OpenAI Fallback

By default the project uses `LocalLLMStub`. To enable OpenAI-backed fallback:

```bash
export USE_OPENAI=1
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5.4-mini
export OPENAI_TEMPERATURE=0.2
python3 main.py
```

## Composite Pipeline Mode

You can request multi-stage composition directly in constraints:

```python
{
  "stage_topologies": ["common_source_res_load", "common_drain"]
}
```

or describe multi-stage intent in the specification and let `TopologyAgent` build a stage plan.

You can optionally provide per-stage constraints:

```python
{
  "stage_topologies": ["diff_pair", "common_source_active_load", "common_drain"],
  "stage_constraints": [
    {"vicm_v": 0.9, "R_load_ohm": 6500.0},
    {"target_gain_db": 16.0},
    {"target_gm_s": 2.5e-3}
  ]
}
```

The selected topology becomes `composite_pipeline` and stage-level topology choices are tracked in:
- `selected_topologies`
- `topology_plan`
- `sizing.stages`

## Benchmarking and pass@k

Run report-grade multi-sample benchmarking:

```bash
python3 evaluation/benchmark_runner.py
BENCH_PROFILE=ti_safe BENCH_SAMPLES=8 BENCH_KS=1,3,5 python3 evaluation/benchmark_runner.py
BENCH_CASES=mirror,common_source,opamp BENCH_SAMPLES=10 BENCH_PROMPT_JITTER=1 python3 evaluation/benchmark_runner.py
```

Outputs are written under `artifacts/benchmarks/...` and include:
- `benchmark_summary.json`
- `benchmark_summary.md`

Key metrics extracted for final reports:
- Sample success rate (`design_validated` plus verification pass)
- First-pass success rate (no refinement loop required)
- pass@k for chosen `k` values
- Topology match rate vs. reference/forced topology
- Verification pass-rate on known checks
- Verification coverage ratio
- Runtime, iteration count, and LLM-call counts
- LLM call success-rate
- Composite stage-count and stage-order match rates

## Paper-Ready Report Export

Export a single CSV and LaTeX table that compares your framework and baselines on the same metric schema:

```bash
python3 evaluation/report_export.py \
  --framework ours=artifacts/benchmarks/<ours_run>/benchmark_summary.json \
  --framework baseline_a=/path/to/baseline_a_summary.json \
  --framework baseline_b=/path/to/baseline_b_summary.json \
  --ks 1,3,5
```

You can also pass a benchmark directory instead of the JSON path; the script will pick `benchmark_summary.json` automatically.

Outputs (under `artifacts/reports/...` by default):
- `framework_comparison.csv`
- `framework_comparison.tex`
- `comparison_schema.json`

Baseline files should follow the same `benchmark_summary.json` structure (at least `overall`, with optional `case_summaries` and `samples`).

## Demo Circuit Catalog

The catalog includes:

- `common_source`
- `two_stage_common_source_res_load`
- `common_drain`
- `common_gate`
- `rc`
- `source_degenerated_amplifier`
- `mirror`
- `wilson_mirror`
- `cascode_mirror`
- `common_source_active_load`
- `cascode_amp`
- `diff_pair`
- `diode_connected_amplifier`
- `mos_buffer`
- `nand2`
- `opamp`
- `sram6t`
- `two_stage_opamp_single_ended`
- `fully_diff_amp_cmfb`
- `lc_oscillator`
- `telescopic_cascode_opamp`
- `folded_cascode_opamp`
- `bandgap_reference`
- `comparator`
- `ti_sensor_frontend_3stage`
- `ti_filter_amp_chain`
- `ti_three_stage_amp`

Notes:

- Strongest native template support today is for `rc`, `mirror`, `common_source`, `diff_pair`, `opamp`, `folded_cascode_opamp`, `gm_stage`, and `comparator`.
- Added verification summaries now cross-check target metrics and first-pass analytical estimates for cutoff, gain, power, current, Vref, oscillation frequency, UGBW, and comparator delay.
- Demo cases are now tagged with readiness so you can keep presentations on the stable subset and leave experimental blocks out of the live path.
- `DEMO_PROFILE=ti_safe` is the recommended Texas Instruments demo profile because it stays on curated, verified cases and excludes the still-experimental Wilson mirror path.
- `DEMO_PROFILE=ti_grand_demo` is the recommended profile for a stronger final showcase with complex cascaded pipelines.

## Regression Tests

Run the regression suite with:

```bash
python3 -m unittest discover -s tests -p 'test_*.py'
```

## Simulation Artifacts

Each run writes under `artifacts/simulations/...` and may include:

- `generated.sp`
- `ngspice.log`
- `ac_out.csv`, `tran_out.csv`, `dc_out.csv`
- `ac_plot.svg`, `tran_plot.svg`, `dc_plot.svg`

The plotting layer falls back to SVG generation if `matplotlib` is unavailable.

## Demo Notes

- The multi-agent progression can be shown with `SHOW_HISTORY=1`, which prints the recent write and agent-execution timeline for a run.
- The orchestration behavior for retries, failures, and refinement loops lives in `flow/design_flow.py`, which is useful backup material during architecture discussions.

## Dataset

This project references the Masala-CHAI SPICE netlist dataset, but the dataset itself is not included in this repository.

## Citation

Bhandari, J., Bhat, V., He, Y., Rahmani, H., Garg, S., & Karri, R. (2025). Masala-CHAI: A Large-Scale SPICE Netlist Dataset for Analog Circuits by Harnessing AI. arXiv:2411.14299.
