# LLM Customized for Analog Circuit Design

## Overview

This repository is a multi-agent analog design demo flow. It takes a circuit goal, selects a topology, sizes a first-pass implementation, validates constraints, generates an ngspice netlist, runs simulation, and stores artifacts for presentation.

The framework is designed for capstone-style demos where we want traceability and repeatable outputs more than full custom-IC signoff accuracy.

## Flow

`Specification -> TopologyAgent -> SizingAgent -> ConstraintAgent -> NetlistAgent -> SimulationAgent -> RefinementAgent`

Each agent reads and writes shared memory so the full design state stays inspectable.

## Repository Structure

- `agents/` - design agents and orchestration logic
- `core/` - shared defaults, memory helpers, topology library, demo case catalog
- `flow/` - lightweight workflow engine
- `flow/design_flow.py` - orchestration graph, retry logic, and refinement loop transitions
- `llm/` - OpenAI-backed and local stub LLM adapters
- `main.py` - run one demo case
- `demo_runner.py` - run a batch of demo cases

## Running

Run the default case:

```bash
python3 main.py
```

List available demo cases:

```bash
DESIGN_CASE=list python3 main.py
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
```

## OpenAI Fallback

By default the project uses `LocalLLMStub`. To enable OpenAI-backed fallback:

```bash
export USE_OPENAI=1
export OPENAI_API_KEY=...
export OPENAI_MODEL=gpt-4.1-mini
python3 main.py
```

## Demo Circuit Catalog

The catalog includes:

- `common_source`
- `two_stage_common_source_res_load`
- `common_drain`
- `common_gate`
- `rc`
- `source_degenerated_amplifier`
- `mirror`
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
- `bandgap_reference`

Notes:

- Strongest native template support today is for `rc`, `mirror`, `common_source`, `diff_pair`, `opamp`, and the `gm_stage` behavioral proxy family.
- Some advanced catalog entries intentionally map to demo proxy models so the framework can still run end-to-end and generate plots in a live presentation.

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
