"""
Fast OCR preprocessing for demo/testing. Processes only the first N images
quickly. Use this to validate the training pipeline while full OCR runs.
"""

import argparse
from pathlib import Path

import easyocr
import torch


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fast OCR preprocessing (limited to first N images for testing)."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/Dataset"))
    parser.add_argument("--output", type=Path, default=Path("data/corpus_sample.txt"))
    parser.add_argument("--limit", type=int, default=50, help="Process only first N images")
    parser.add_argument("--lang", type=str, default="en")
    parser.add_argument("--min-chars", type=int, default=10)
    return parser.parse_args()


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def run_ocr(input_dir: Path, min_chars: int, language: str, limit: int):
    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    image_paths = sorted(p for p in input_dir.rglob("*") if p.is_file() and is_image_file(p))[:limit]
    if not image_paths:
        raise ValueError(f"No image files found in: {input_dir}")

    # CPU mode for stability
    reader = easyocr.Reader([language], gpu=False, verbose=False)

    collected = []
    skipped = 0
    failed = 0

    for idx, image_path in enumerate(image_paths, 1):
        try:
            print(f"[{idx}/{len(image_paths)}] Processing {image_path.name}...", flush=True)
            lines = reader.readtext(str(image_path), detail=0, paragraph=True)
            text = "\n".join(lines)
            cleaned = text.strip()
            if len(cleaned) < min_chars:
                skipped += 1
                continue

            collected.append(f"\n\n### SOURCE: {image_path.name}\n{cleaned}\n")
        except Exception as e:
            print(f"  ERROR processing {image_path.name}: {e}", flush=True)
            failed += 1
            continue

    return collected, len(image_paths), skipped, failed


def main():
    args = parse_args()

    chunks, total_images, skipped, failed = run_ocr(
        args.input_dir,
        args.min_chars,
        args.lang,
        args.limit,
    )
    if not chunks:
        raise ValueError(
            "OCR completed, but all files were filtered out. "
            "Lower --min-chars or use higher quality images."
        )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(chunks), encoding="utf-8")

    print(f"\nOCR Complete (Sample):")
    print(f"  Processed images: {total_images}")
    print(f"  Successful: {len(chunks)}")
    print(f"  Skipped (too little text): {skipped}")
    print(f"  Failed (errors): {failed}")
    print(f"  Wrote corpus: {args.output}")


if __name__ == "__main__":
    main()
