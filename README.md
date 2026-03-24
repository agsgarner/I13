# LLM Customized for Analog Circuit Design

## Overview

This repository contains a modular, multi-agent framework for analog filter design.

The system demonstrates how structured AI agents can collaborate through shared memory to:

- Interpret design specifications
- Select circuit topologies
- Size components
- Validate constraints
- Perform lightweight simulation
- Log design state transitions

The focus of this project is architectural structure, orchestration, and traceability

---

## System Architecture

The framework follows a shared-memory multi-agent pattern:


Specification -> TopologyAgent -> SizingAgent -> ConstraintAgent -> SimulationAgent -> RefinementAgent -> OrchestrationAgent


Each agent:
- Reads from shared memory
- Writes structured outputs
- Logs state transitions

The OrchestrationAgent coordinates execution and validation flow.

---

## Repository Structure

- `agents/` — Independent design agents and workflow control
- `memory/` — Shared state and history logging
- `core/` — Structured design state and memory between agents
- `main.py` — Entry point and design summary output

---

# LLM Customized for Analog Circuit Design

## Overview

This repository contains a modular, multi-agent framework for analog filter design.

The system demonstrates how structured AI agents can collaborate through shared memory to:

- Interpret design specifications  
- Select circuit topologies  
- Size components  
- Validate constraints  
- Perform lightweight simulation  
- Log design state transitions  

The focus of this project is architectural structure, orchestration, and traceability within an AI-assisted analog design workflow.

---

## System Architecture

The framework follows a shared-memory multi-agent pattern:

Specification  
→ TopologyAgent  
→ SizingAgent  
→ ConstraintAgent  
→ SimulationAgent  
→ RefinementAgent  
→ OrchestrationAgent  

Each agent:
- Reads from shared memory  
- Writes structured outputs  
- Logs state transitions  

The OrchestrationAgent coordinates execution and validation flow.

---

## Repository Structure

- `agents/` — Independent design agents and workflow control  
- `memory/` — Shared state and history logging  
- `core/` — Structured design state and memory between agents  
- `main.py` — Entry point and design summary output  

---

## Example Use Case

Input:

> Design a lowpass filter with 1kHz cutoff

Output:

- Selected topology: RC lowpass
- Computed component values
- Constraint validation report
- Estimated cutoff frequency
- Final design status

---

## Key Concepts

### Shared Memory

All agents communicate via a centralized memory object.  
Each write operation is timestamped and stored in history.

This enables:

- Traceability
- Debugging
- Lifecycle inspection
- Retry logic support

---

### Design Status Model

A structured design status enum tracks the current state of the pipeline:

- topology_selected
- design_invalid
- design_validated
- simulation_complete
- orchestration_failed

---

## Getting Started

### 1. Clone and enter the repo

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME
```

### 2. Python

- **Python 3.9+** required.
- Optional: create a virtual environment:
  ```bash
  python -m venv .venv
  .venv\Scripts\activate   # Windows
  # source .venv/bin/activate   # Linux/macOS
  ```
- Install dependencies (Streamlit for the web UI):
  ```bash
  pip install -r requirements.txt
  ```

### 3. ngspice (optional)

The pipeline always writes an RC netlist and computes **fc** analytically. It **runs ngspice** when:

- You set **`NGSPICE_CMD`** to a non-empty path/command, or
- **Windows only:** `NGSPICE_CMD` is unset and `ngspice_con.exe` exists at the default path used in `simulation_agent.py` (edit that constant if your install differs).

- **Without ngspice** (no env var and no default exe): simulation completes with `fc_hz_analytic`; `spice_skipped: true` (no external simulator).
- **With `NGSPICE_CMD`**: install ngspice locally, then point the variable at the executable:
  - **Linux**: e.g. `sudo apt install ngspice`, then `export NGSPICE_CMD=ngspice`
  - **macOS**: e.g. `brew install ngspice`, then `export NGSPICE_CMD=ngspice`
  - **Windows**: use the **console** binary `ngspice_con.exe`, e.g.:
    ```powershell
    $env:NGSPICE_CMD = "C:\path\to\ngspice_con.exe"
    ```
    or add its folder to PATH and use `$env:NGSPICE_CMD = "ngspice_con"`.

Download: [ngspice](https://ngspice.sourceforge.io/download.html).

### 4. Run

**Command line:**

```bash
python main.py
```

**Web UI (Streamlit):**

```bash
streamlit run app.py
```

Then open the URL shown (e.g. http://localhost:8501), enter a spec and target cutoff, and click **Run design**.

---

## Dataset

This project utilizes the Masala-CHAI large-scale SPICE netlist dataset for analog circuits.

The dataset is **not included in this repository**.

To use the dataset:

1. Download it from the official Masala-CHAI repository.
2. Extract it into a local `data/` directory.
3. Ensure `data/` is excluded via `.gitignore`.

The dataset is omitted to:
- Avoid repository bloat  
- Maintain clean version control  
- Follow best practices for ML research repositories  

---

## Project Goals

- Demonstrate structured AI orchestration
- Enforce constraint-aware validation
- Model design lifecycle state transitions
- Simulate an AI-assisted EDA workflow

---

## Future Extensions

- Additional filter topologies
- SPICE integration
- Optimization loops
- Multi-stage filter synthesis
- Expanded constraint reasoning

---

## Citation

If you use the Masala-CHAI dataset in your work, please cite:

Bhandari, J., Bhat, V., He, Y., Rahmani, H., Garg, S., & Karri, R. (2025).
Masala-CHAI: A Large-Scale SPICE Netlist Dataset for Analog Circuits by Harnessing AI.
arXiv:2411.14299.

BibTeX:

@misc{bhandari2025masalachailargescalespicenetlist,
      title={Masala-CHAI: A Large-Scale SPICE Netlist Dataset for Analog Circuits by Harnessing AI}, 
      author={Jitendra Bhandari and Vineet Bhat and Yuheng He and Hamed Rahmani and Siddharth Garg and Ramesh Karri},
      year={2025},
      eprint={2411.14299},
      archivePrefix={arXiv},
      primaryClass={cs.AR},
      url={https://arxiv.org/abs/2411.14299}
}

## Authors

Austin Garner,
Manasvi Perisetty,
Anika Sridhar,
Emmanuel Martinez,
Arohan Shrestha,
Emmanuel Ramirez
