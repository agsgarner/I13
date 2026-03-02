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

## Running the Project


python main.py


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
*Masala-CHAI: A Large-Scale SPICE Netlist Dataset for Analog Circuits by Harnessing AI*.  
arXiv:2411.14299.

BibTeX:

```bibtex
@misc{bhandari2025masalachailargescalespicenetlist,
      title={Masala-CHAI: A Large-Scale SPICE Netlist Dataset for Analog Circuits by Harnessing AI}, 
      author={Jitendra Bhandari and Vineet Bhat and Yuheng He and Hamed Rahmani and Siddharth Garg and Ramesh Karri},
      year={2025},
      eprint={2411.14299},
      archivePrefix={arXiv},
      primaryClass={cs.AR},
      url={https://arxiv.org/abs/2411.14299}
}

---

## Authors

Austin Garner,
Manasvi Perisetty,
Anika Sridhar,
Emmanuel Martinez,
Arohan Shrestha,
Emmanuel Ramirez
