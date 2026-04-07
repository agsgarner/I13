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


Specification -> TopologyAgent -> SizingAgent -> ConstraintAgent -> NetlistAgent -> SimulationAgent -> RefinementAgent


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
→ NetlistAgent
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

## Running the Project


python main.py


---

## External LLM Backends

By default, `main.py` uses `LocalLLMStub`.

Enable OpenAI:

```powershell
$env:LLM_PROVIDER="openai"
$env:OPENAI_API_KEY="<your-key>"
$env:OPENAI_MODEL="gpt-4.1-mini"
python main.py
```

Enable Qwen (DashScope compatible endpoint):

```powershell
$env:LLM_PROVIDER="qwen"
$env:QWEN_API_KEY="<your-key>"
$env:QWEN_MODEL="qwen-turbo"
python main.py
```

Optional Qwen endpoint override:

```powershell
$env:QWEN_BASE_URL="https://dashscope-intl.aliyuncs.com/compatible-mode/v1/chat/completions"
```

Legacy toggles still supported:

- `USE_OPENAI=1`
- `USE_QWEN=1`

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

## Transformer Training (PyTorch)

This repository now includes a minimal character-level Transformer language model.

### 1) Install Dependencies

```powershell
cd I13
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### 2) Prepare Dataset

Create a UTF-8 text file at:

- `data/corpus.txt`

You can combine multiple text sources into that file.

If your source data is in images (`.jpg`, `.jpeg`, `.png`), run OCR preprocessing first.

### OCR Preprocessing (Images -> Text)

OCR means "Optical Character Recognition": it reads text from images and converts it into machine-readable text.

1. Put images in `data/images/`
2. Run:

```powershell
python ocr_preprocess.py --input-dir data/images --output data/corpus.txt
```

Optional flags:

```powershell
python ocr_preprocess.py --input-dir data/images --output data/corpus.txt --lang en --gpu
```

This OCR pipeline uses EasyOCR and does not require a separate external OCR executable.

### 3) Train

```powershell
python train_transformer.py --data data/corpus.txt --epochs 8
```

### Baseline with Masala-CHAI (Caption -> SPICE)

If you have `masala-chai-dataset-new/` in the workspace root, you can build a baseline corpus using the config-based preparation pipeline.

1. Build corpus and pair file:

```powershell
python prepare_generic_corpus.py --config dataset_configs\masala_chai.yaml
```

This creates:

- `data/corpus_masala_baseline.txt` for language-model training
- `data/masala_pairs.jsonl` for later supervised experiments/evaluation

2. Train baseline model (fast version for local testing):

```powershell
python prepare_generic_corpus.py --config dataset_configs\masala_chai.yaml --max-samples 500 --shuffle
python train_transformer.py --data data/corpus_masala_baseline.txt --epochs 4 --block-size 128
```

3. Generate with a task-style prompt:

```powershell
python generate.py --checkpoint char_transformer.pt --prompt "### Task\nGenerate a SPICE netlist from the schematic description.\n\n### Description\nA common-emitter NPN stage with collector resistor and emitter resistor.\n\n### SPICE\n" --max-new-tokens 300 --temperature 0.7 --top-k 40
```

### Generic Dataset Preparation (Config-Based)

For custom datasets or to reuse the pipeline with different data sources, use the config-based approach:

1. Create a YAML config file (see `dataset_configs/masala_chai.yaml` for example):

```yaml
dataset_root: "../your-dataset"
mapping_file: "data_mapping.json"

input_fields:
  - name: "input_text"
    file_key: "input"      # Read from file
  - name: "output_text"
    file_key: "output"
  - name: "task_name"
    literal: "translation" # Literal string

template: |
  ### Task: {task_name}
  ### Input
  {input_text}
  ### Output
  {output_text}
  <END>

output_corpus: "data/corpus_custom.txt"
output_jsonl: "data/pairs_custom.jsonl"
```

2. Run the generic preparation script:

```powershell
python prepare_generic_corpus.py --config dataset_configs/your_config.yaml
```

Optional flags:

```powershell
python prepare_generic_corpus.py --config dataset_configs/your_config.yaml --max-samples 500 --shuffle
```

3. Train as usual:

```powershell
python train_transformer.py --data data/corpus_custom.txt --epochs 8
```

**Config field types:**
- `file_key`: Read content from file path in JSON mapping
- `json_key`: Use value directly from JSON (for metadata/labels)
- `literal`: Insert a constant string

This saves a checkpoint at:

- `char_transformer.pt`

### 4) Generate Text

```powershell
python generate.py --checkpoint char_transformer.pt --prompt "Design a" --max-new-tokens 200
```

You can control sampling with:

- `--temperature 0.8`
- `--top-k 40`

---

## Project Goals

- Demonstrate structured AI orchestration
- Enforce constraint-aware validation
- Model design lifecycle state transitions
- Simulate an AI-assisted EDA workflow

---

## Future Extensions

- Additional filter topologies
- Optimization loops
- Multi-stage filter synthesis
- Expanded constraint reasoning

---

## Citation

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
