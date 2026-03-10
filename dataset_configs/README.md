# Dataset Configuration Guide

This folder contains YAML configuration files for the generic corpus preparation pipeline.

## Quick Start

```powershell
python prepare_generic_corpus.py --config dataset_configs/masala_chai.yaml
```

## Configuration Schema

### Required Fields

```yaml
dataset_root: "../path-to-dataset"  # Root directory containing your data
mapping_file: "data_mapping.json"   # JSON file with sample metadata
input_fields: [...]                  # List of fields to extract (see below)
template: |                          # How to format each training sample
  Your template here with {placeholders}
```

### Optional Fields

```yaml
output_corpus: "data/corpus.txt"    # Default: data/corpus.txt
output_jsonl: "data/pairs.jsonl"    # Default: data/pairs.jsonl
```

## Input Field Types

### 1. File-based (`file_key`)
Reads content from a text file whose path is in the JSON mapping.

```yaml
- name: "caption"
  file_key: "caption"  # JSON has: {"caption": "path/to/caption.txt"}
```

**Mapping JSON example:**
```json
[
  {
    "caption": "captions/cap1.txt",
    "spice": "spice/spice1.txt"
  }
]
```

### 2. Direct JSON value (`json_key`)
Uses the value directly from the JSON mapping (for metadata, labels, or inline text).

```yaml
- name: "difficulty"
  json_key: "difficulty"  # JSON has: {"difficulty": "hard"}
```

**Mapping JSON example:**
```json
[
  {
    "question": "What is Ohm's law?",
    "answer": "V = IR",
    "difficulty": "beginner"
  }
]
```

### 3. Literal string (`literal`)
Inserts the same constant value for every sample.

```yaml
- name: "task_instruction"
  literal: "Generate SPICE from description"
```

## Template Syntax

Use Python `str.format()` style placeholders: `{field_name}`

**Example:**

```yaml
template: |
  ### Task: {task_type}
  
  ### Input
  {input_text}
  
  ### Expected Output
  {output_text}
  
  ### Metadata
  Difficulty: {difficulty}
  <END_SAMPLE>
```

All fields referenced in the template must be defined in `input_fields`.

## Command-Line Overrides

Override config values at runtime:

```powershell
# Override dataset root
python prepare_generic_corpus.py --config my_config.yaml --dataset-root ../other-dataset

# Override output paths
python prepare_generic_corpus.py --config my_config.yaml --output-corpus data/custom.txt

# Limit samples and shuffle
python prepare_generic_corpus.py --config my_config.yaml --max-samples 1000 --shuffle --seed 123
```

## Example Configs

- **`masala_chai.yaml`** — Circuit caption → SPICE netlist (file-based)
- **`example_qa.yaml`** — Question answering with inline JSON (json_key + literal)

## Creating Your Own Config

1. **Inspect your data structure**
   ```powershell
   cat your_dataset/data_mapping.json | head -20
   ```

2. **Identify field types**
   - File paths → use `file_key`
   - Direct values → use `json_key`
   - Constants → use `literal`

3. **Design your template**
   - Structure affects model learning
   - Use clear delimiters (`### Section`)
   - End with a unique marker (`<END_SAMPLE>`)

4. **Test with small sample**
   ```powershell
   python prepare_generic_corpus.py --config your_config.yaml --max-samples 10
   cat data/corpus.txt  # Verify output format
   ```

5. **Run full preparation**
   ```powershell
   python prepare_generic_corpus.py --config your_config.yaml
   ```

## Troubleshooting

**Error: "Config missing required key"**
- Ensure `dataset_root`, `mapping_file`, `input_fields`, and `template` are all present

**Error: "Mapping file not found"**
- Check that `mapping_file` path is relative to `dataset_root`

**Error: "Template references missing field"**
- All `{placeholders}` in template must match a field `name` in `input_fields`

**No valid samples loaded**
- Check file paths in your JSON mapping
- Verify files actually exist
- Ensure files contain non-empty text
