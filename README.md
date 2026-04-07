# Multi-Agent Analog Circuit Design (I13)

## Overview

This project is a multi-agent analog design demo flow.

Given a specification, the system:

1. selects a topology,
2. sizes a first-pass circuit,
3. validates constraints,
4. generates an ngspice netlist,
5. runs simulation, and
6. applies refinement logic.

The current recommended LLM backend is **Qwen API** (DashScope-compatible endpoint).

---

## Architecture

Flow:

`TopologyAgent -> SizingAgent -> ConstraintAgent -> NetlistAgent -> SimulationAgent -> RefinementAgent`

Orchestration is handled by `OrchestrationAgent` using shared memory state.

---

## Repository Layout

- `agents/` - workflow agents
- `core/` - shared state, defaults, topology/demo catalog
- `flow/` - flow engine and orchestration graph
- `llm/` - LLM adapters (`qwen_llm.py`, `openai_llm.py`, local stub)
- `spicefiles/` - SPICE helpers/assets
- `main.py` - primary entry point
- `requirements.txt` - Python dependencies

---

## Setup

Run from the folder that contains `main.py`.

```powershell
cd C:\Users\emman\LLM_Construction\I13
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If ngspice is not on PATH, set it explicitly:

```powershell
$env:NGSPICE_PATH="C:\Program Files\ngspice-46_64\Spice64\bin\ngspice.exe"
```

---

## Qwen API Configuration (Recommended)

```powershell
$env:LLM_PROVIDER="qwen"
$env:QWEN_API_KEY="<your-dashscope-key>"
$env:QWEN_MODEL="qwen-turbo"
```

Optional endpoint override:

```powershell
$env:QWEN_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
```

Run:

```powershell
python main.py
```

---

## Run Modes

### 1) Default single run

```powershell
python main.py
```

### 2) List built-in demo cases

```powershell
python main.py --list-cases
```

### 3) Run a specific demo case

```powershell
python main.py --demo-case rc
python main.py --demo-case mirror
python main.py --demo-case diff_pair
python main.py --demo-case opamp
```

### 4) Quick custom RC-style run

```powershell
python main.py --spec "Design a first-order low-pass filter with 2 kHz cutoff" --circuit-type rc_lowpass --target-fc 2000
```

For non-RC circuits, prefer `--demo-case` because those topologies require richer constraint sets.

---

## Output Artifacts

Simulation outputs are written under:

`artifacts/simulations/<timestamp>/`

Typical files include:

- `generated.sp`
- `ngspice.log`
- `stdout.txt`, `stderr.txt`
- CSV/plot files when available

---

## Troubleshooting

### Qwen fallback to local stub

If you see:

`Qwen unavailable, falling back to LocalLLMStub`

check:

1. `QWEN_API_KEY` is set in the current shell,
2. key is valid for DashScope,
3. endpoint and model are correct (`qwen-turbo`),
4. outbound network access is available.

### ngspice not found

Set `NGSPICE_PATH` to your `ngspice.exe` full path.

### Wrong working directory

If Python tries to open `I13\I13\main.py`, you are one folder too deep.
Run from the `I13` directory that directly contains `main.py`.

---

## Notes

- The current workflow is configured around API-backed inference (Qwen/OpenAI) plus local simulation.
- Local OCR/training scripts were removed as cleanup in this branch.

---

## Citation

Bhandari, J., Bhat, V., He, Y., Rahmani, H., Garg, S., & Karri, R. (2025).  
Masala-CHAI: A Large-Scale SPICE Netlist Dataset for Analog Circuits by Harnessing AI.  
arXiv:2411.14299.
