import argparse
import json
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a corpus from any dataset using a YAML configuration."
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to dataset config YAML file.",
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
        help="Override dataset root directory from config.",
    )
    parser.add_argument(
        "--output-corpus",
        type=Path,
        default=None,
        help="Override output corpus path from config.",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=None,
        help="Override output JSONL path from config.",
    )
    parser.add_argument(
        "--max-samples",
        type=int,
        default=0,
        help="Use first N valid samples only. 0 means use all.",
    )
    parser.add_argument(
        "--shuffle",
        action="store_true",
        help="Shuffle samples before saving.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for shuffling.",
    )
    return parser.parse_args()


def load_config(config_path: Path) -> Dict[str, Any]:
    """Load and validate YAML configuration."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    
    with config_path.open("r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    
    required_keys = ["dataset_root", "mapping_file", "input_fields", "template"]
    for key in required_keys:
        if key not in config:
            raise ValueError(f"Config missing required key: {key}")
    
    return config


def read_text_file(path: Path) -> str:
    """Read text file with error handling."""
    return path.read_text(encoding="utf-8", errors="ignore").strip()


def resolve_field_value(
    item: Dict[str, Any],
    field_config: Dict[str, str],
    dataset_root: Path,
) -> Optional[str]:
    """
    Resolve a field value based on configuration.
    
    field_config can specify:
    - file_key: read from file path in JSON
    - json_key: read directly from JSON value
    - literal: use a literal string value
    """
    if "file_key" in field_config:
        file_key = field_config["file_key"]
        if file_key not in item:
            return None
        
        file_path = dataset_root / item[file_key]
        if not file_path.exists():
            return None
        
        return read_text_file(file_path)
    
    elif "json_key" in field_config:
        json_key = field_config["json_key"]
        return item.get(json_key)
    
    elif "literal" in field_config:
        return field_config["literal"]
    
    return None


def load_samples(
    dataset_root: Path,
    mapping_file: str,
    input_fields: List[Dict[str, Any]],
) -> List[Dict[str, str]]:
    """Load and process samples based on configuration."""
    mapping_path = dataset_root / mapping_file
    
    if not mapping_path.exists():
        raise FileNotFoundError(f"Mapping file not found: {mapping_path}")
    
    mapping = json.loads(mapping_path.read_text(encoding="utf-8"))
    
    if not isinstance(mapping, list):
        raise ValueError("Mapping file must contain a JSON array.")
    
    samples: List[Dict[str, str]] = []
    skipped = 0
    
    for idx, item in enumerate(mapping):
        if not isinstance(item, dict):
            continue
        
        sample = {"id": str(idx + 1)}
        valid = True
        
        for field in input_fields:
            field_name = field["name"]
            field_value = resolve_field_value(item, field, dataset_root)
            
            if field_value is None or not field_value.strip():
                valid = False
                break
            
            sample[field_name] = field_value
        
        if valid:
            samples.append(sample)
        else:
            skipped += 1
    
    print(f"Loaded valid samples: {len(samples)}")
    if skipped > 0:
        print(f"Skipped invalid/missing records: {skipped}")
    
    return samples


def format_sample(sample: Dict[str, str], template: str) -> str:
    """Format a sample using the template string."""
    try:
        return template.format(**sample)
    except KeyError as e:
        raise ValueError(f"Template references missing field: {e}")


def build_corpus(samples: List[Dict[str, str]], template: str) -> str:
    """Build corpus text from samples and template."""
    blocks = [format_sample(sample, template) for sample in samples]
    return "\n\n".join(blocks) + "\n"


def write_outputs(
    samples: List[Dict[str, str]],
    template: str,
    output_corpus: Path,
    output_jsonl: Path,
) -> None:
    """Write corpus and JSONL outputs."""
    output_corpus.parent.mkdir(parents=True, exist_ok=True)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    
    # Write corpus
    corpus_text = build_corpus(samples, template)
    output_corpus.write_text(corpus_text, encoding="utf-8")
    
    # Write JSONL
    with output_jsonl.open("w", encoding="utf-8") as f:
        for sample in samples:
            f.write(json.dumps(sample, ensure_ascii=False) + "\n")
    
    print(f"Saved corpus: {output_corpus} ({len(corpus_text)} bytes)")
    print(f"Saved JSONL: {output_jsonl} ({len(samples)} samples)")


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    
    # Resolve paths (CLI args override config)
    dataset_root = (
        args.dataset_root.resolve()
        if args.dataset_root
        else Path(config["dataset_root"]).resolve()
    )
    
    output_corpus = (
        args.output_corpus
        if args.output_corpus
        else Path(config.get("output_corpus", "data/corpus.txt"))
    )
    
    output_jsonl = (
        args.output_jsonl
        if args.output_jsonl
        else Path(config.get("output_jsonl", "data/pairs.jsonl"))
    )
    
    # Load samples
    samples = load_samples(
        dataset_root=dataset_root,
        mapping_file=config["mapping_file"],
        input_fields=config["input_fields"],
    )
    
    if not samples:
        raise RuntimeError("No valid samples found. Check dataset paths and config.")
    
    # Optional shuffle
    if args.shuffle:
        import random
        rng = random.Random(args.seed)
        rng.shuffle(samples)
    
    # Optional limit
    if args.max_samples > 0:
        samples = samples[:args.max_samples]
        print(f"Limited to first {len(samples)} samples")
    
    # Write outputs
    write_outputs(samples, config["template"], output_corpus, output_jsonl)


if __name__ == "__main__":
    main()
