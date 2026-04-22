# LLM Customized for Analog Circuit Design

## Overview

This repository is a multi-agent analog design demo flow. It takes a circuit goal, selects a topology, sizes a first-pass implementation, validates constraints, generates an ngspice netlist, runs simulation, and stores artifacts for presentation.

The framework is designed for capstone-style demos where we want traceability and repeatable outputs more than full custom-IC signoff accuracy.

## Flow

`Specification -> TopologyAgent -> SizingAgent -> ConstraintAgent -> NetlistAgent -> OpPointAgent -> SimulationAgent -> RefinementAgent`

Each agent reads and writes shared memory so the full design state stays inspectable.

New in this version:
- Added `python3 main.py preflight` for environment readiness checks before demos.
- Added `python3 main.py showcase` as the final curated TI demo flow with per-case sponsor-review summaries and one aggregate rollup.
- Added `python3 main.py showcase-backup` as a deterministic backup path that still generates polished artifacts even when simulation is intentionally skipped or unavailable.
- Added `python3 main.py demo-safe` to run curated high-confidence cases with sponsor-friendly summaries.
- Added profile sanity checks to `preflight` (topology -> sizing -> constraints -> netlist on representative profile cases).
- Added `--max-cases` runtime guard to `demo-safe` for predictable sponsor-demo runtimes.
- Added deterministic rule-based fallback when a configured LLM backend is unavailable.
- Added graceful degraded execution when ngspice is missing (topology/sizing/netlist still produced).
- Added stage-labeled terminal output to make live walkthroughs easier.
- `TopologyAgent` now supports LLM-assisted stage planning with a topology-preserving `topology_plan`.
- `TopologyAgent` now accepts per-stage constraint payloads via `constraints.stage_constraints`.
- The flow supports `composite_pipeline` designs that cascade multiple topology blocks.
- `NetlistAgent` now emits stage markers and validates stage-count/order continuity for cascaded netlists.
- Core op-amp, gm-stage, and comparator templates now use transistor-level first-pass netlists instead of behavioral placeholders.
- `RefinementAgent` can use LLM guidance to suggest bounded numeric sizing updates when deterministic refinement stalls.
- Expanded topology support for TI-style analog building blocks including mirror variants, differential-front-end variants, op-amp cores, ADC/DAC support blocks, power helper blocks, comparators, and active filter stages.
- Added a structured reference-knowledge subsystem that ingests local JSON, YAML, and Markdown files from `references/knowledge` and `references/schemas`.
- Agents now retrieve topology notes, design equations, device heuristics, example netlists, cookbook circuits, templates, and evaluation criteria through a shared catalog interface.
- Vendor-neutral starter schemas are included for cookbook circuits, op-amp templates, current mirror templates, ADC/DAC driver templates, and power helper templates.

## Repository Structure

- `agents/` - design agents and orchestration logic
- `core/` - shared defaults, memory helpers, topology library, demo case catalog, preflight/runtime helpers
- `references/knowledge/` - structured reference bundles and topology notes used by retrieval
- `references/schemas/` - starter schema definitions for extending the reference library
- `flow/` - lightweight workflow engine
- `flow/design_flow.py` - orchestration graph, retry logic, and refinement loop transitions
- `llm/` - OpenAI-backed and local stub LLM adapters
- `main.py` - run one demo case
- `demo_runner.py` - run a batch of demo cases
- `evaluation/benchmark_runner.py` - pass@k-oriented benchmark harness for report-ready evaluation

## Running

List available design cases and profiles:

```bash
python3 main.py list-cases
python3 main.py list-profiles
```

Run an environment preflight before a demo:

```bash
python3 main.py preflight
python3 main.py preflight --strict
```

`preflight` checks:
- Python version
- required Python packages for the configured LLM backend (from `requirements*.txt`)
- ngspice availability
- writable artifacts directory
- configured and resolved LLM backend
- available device/model libraries
- profile sanity on representative cases for the selected profile

Run the final TI live-demo command:

```bash
python3 main.py showcase
```

Run the backup demo command:

```bash
python3 main.py showcase-backup
```

The final showcase is curated around the currently strongest stable cases:

- `rc` - passive baseline with clean cutoff verification and easy-to-read AC/transient plots
- `mirror` - transistor-level current-bias generation with DC current-copy verification
- `common_source` - single-stage transistor-level gain block with visible refinement and AC/transient metrics
- `folded_cascode_opamp` - strongest currently stable higher-value analog block with gain, UGBW, and phase-margin extraction
- `bandgap_reference` - precision-reference style block with Vref-focused verification
- `comparator` - dynamic decision block with transient delay verification

The showcase intentionally omits the current composite pipelines and the two-stage Miller op-amp from the live path because they are not yet the most reliable fully verified sponsor-facing examples.

Run the broader sponsor-safe curated command:

```bash
python3 main.py demo-safe
python3 main.py demo-safe --cases rc,mirror,opamp
python3 main.py demo-safe --profile ti_block_library_safe --max-cases 5
```

Run one specific case:

```bash
python3 main.py run-case --case mirror
SHOW_HISTORY=1 DESIGN_CASE=mirror python3 main.py
```

Run a batch demo artifact sweep:

```bash
DEMO_LIMIT=4 python3 demo_runner.py
DESIGN_CASES=mirror,opamp,common_source,diff_pair python3 demo_runner.py
DEMO_PROFILE=ti_safe python3 demo_runner.py
DEMO_PROFILE=ti_final_demo python3 demo_runner.py
STABLE_ONLY=1 python3 demo_runner.py
DEMO_PROFILE=list python3 demo_runner.py
```

## LLM Backend and Fallback

The default backend is deterministic rule-based planning (`LLM_BACKEND=rule_based`), which is robust for demos and does not require cloud/API access.

To use OpenAI:

```bash
export LLM_BACKEND=openai
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-5.4-mini
export OPENAI_TEMPERATURE=0.2
python3 main.py
```

You can also force the old local stub behavior:

```bash
export LLM_BACKEND=local_stub
python3 main.py
```

If `LLM_BACKEND=openai` is configured but unavailable (missing package/API key/init failure), the system now degrades automatically to deterministic rule-based planning.

## Structured Reference Knowledge

The runtime now loads a shared reference catalog at startup. By default it scans:

- `references/knowledge`
- `references/schemas`

Supported file types:

- `.json`
- `.yaml` / `.yml`
- `.md` / `.markdown`

YAML loading uses `PyYAML` when installed; JSON and Markdown work with the base dependency set.

The catalog is injected into the agents so topology selection, sizing, netlist generation, and verification can retrieve reusable structured knowledge. To point the runtime at additional folders, set:

```bash
export I13_REFERENCE_PATHS=references/knowledge:references/schemas:/path/to/more_refs
```

This is the intended extension point for future TI-specific references and model metadata. The current starter content stays vendor-neutral.

## Graceful Degradation

- If `ngspice` is unavailable, the flow still produces topology, sizing, and generated netlist artifacts.
- In degraded mode, OP and simulation stages are marked as skipped with explicit reasons in reports.
- If an LLM backend is unavailable, the flow falls back to deterministic rule-based planning.

## Terminal Output

Live stage labels are now printed for each run:

```text
[Stage] TopologyAgent: starting
[Stage] TopologyAgent: topology_selected
...
```

This is designed to make sponsor walk-throughs easier to narrate. Set `I13_STAGE_OUTPUT=0` to disable stage labels.

The `showcase` and `showcase-backup` commands add a second presentation layer after each case with:

- topology-choice reasoning
- concise sizing summary
- simulation status
- extracted metrics
- requirement-by-requirement verdicts
- per-case final result
- sponsor-review Markdown and JSON summaries

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
- `static_comparator`
- `latched_comparator`
- `wide_swing_mirror`
- `diff_pair_resistor_load`
- `diff_pair_current_mirror_load`
- `diff_pair_active_load`
- `telescopic_cascode_core`
- `folded_cascode_core`
- `adc_input_buffer`
- `adc_anti_alias_rc`
- `adc_reference_buffer`
- `transimpedance_frontend`
- `dac_output_buffer`
- `dac_reference_conditioning`
- `ldo_error_amp_core`
- `compensation_network_helper`
- `current_sense_amp_helper`
- `active_filter_stage`
- `ti_sensor_frontend_3stage`
- `ti_filter_amp_chain`
- `ti_three_stage_amp`

Notes:

- Strongest native template support today is for `rc`, mirror variants, `common_source`, differential-pair variants, op-amp families, `bandgap_reference`, comparator variants, ADC/DAC helper blocks, and composite pipelines.
- Added verification summaries now cross-check target metrics and first-pass analytical estimates for cutoff, gain, power, current, Vref, oscillation frequency, UGBW, and comparator delay.
- `python3 main.py showcase` is the recommended final TI live-demo command because it stays on the strongest currently stable and visually clear cases.
- `python3 main.py showcase-backup` is the recommended fallback if you need to preserve the narrative while intentionally deferring simulation.
- Demo cases are now tagged with readiness so you can keep presentations on the stable subset and leave experimental blocks out of the live path.
- `DEMO_PROFILE=ti_safe` is the recommended Texas Instruments demo profile because it stays on curated, verified cases and excludes the still-experimental Wilson mirror path.
- `DEMO_PROFILE=ti_final_demo` is the recommended profile for a stronger final showcase with complex cascaded pipelines.
- `DEMO_PROFILE=ti_block_library_safe` exercises the expanded analog block library with sponsor-friendly cases.
- `DEMO_PROFILE=ti_data_converter_chain` focuses on ADC/DAC support blocks and comparator behavior.
- `DEMO_PROFILE=ti_power_analog` focuses on power-oriented analog helpers (LDO error amp, compensation helper, current-sense helper, references).

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
- `artifacts/showcase_runs/latest_showcase_summary.md` is the stable aggregate summary file to open after a primary showcase run.
- `artifacts/showcase_runs/latest_showcase_backup_summary.md` is the stable aggregate summary file to open after a backup showcase run.
- `artifacts/showcase_runs/latest_showcase_cases/<case>.md` contains the sponsor-facing per-case summaries for the primary showcase.

## Dataset

This project references the Masala-CHAI SPICE netlist dataset, but the dataset itself is not included in this repository.

## Citation

Bhandari, J., Bhat, V., He, Y., Rahmani, H., Garg, S., & Karri, R. (2025). Masala-CHAI: A Large-Scale SPICE Netlist Dataset for Analog Circuits by Harnessing AI. arXiv:2411.14299.
