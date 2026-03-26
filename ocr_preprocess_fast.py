"""
Fast OCR preprocessing for demo/testing. Processes only the first N images
quickly. Use this to validate the training pipeline while full OCR runs.
"""

import argparse
from pathlib import Path

import easyocr
import torch
import cv2


def parse_args():
    parser = argparse.ArgumentParser(
        description="Fast OCR preprocessing (limited to first N images for testing)."
    )
    parser.add_argument("--input-dir", type=Path, default=Path("data/Dataset"))
    parser.add_argument(
        "--input-file",
        type=Path,
        default=None,
        help="Process one specific image file instead of scanning a directory.",
    )
    parser.add_argument("--output", type=Path, default=Path("data/corpus_sample.txt"))
    parser.add_argument("--limit", type=int, default=50, help="Process only first N images")
    parser.add_argument("--lang", type=str, default="en")
    parser.add_argument("--min-chars", type=int, default=10)
    parser.add_argument(
        "--upscale",
        type=float,
        default=1.0,
        help="Optional image upscaling factor (e.g. 2.0 or 3.0) for tiny text.",
    )
    parser.add_argument(
        "--beamsearch",
        action="store_true",
        help="Use beamsearch decoder for harder OCR cases.",
    )
    return parser.parse_args()


def is_image_file(path: Path) -> bool:
    return path.suffix.lower() in {".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp"}


def _collect_image_paths(input_dir: Path, input_file: Path | None, limit: int):
    if input_file is not None:
        if not input_file.exists() or not input_file.is_file():
            raise FileNotFoundError(f"Input file not found: {input_file}")
        if not is_image_file(input_file):
            raise ValueError(f"Input file is not a supported image: {input_file}")
        return [input_file]

    if not input_dir.exists():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    return sorted(p for p in input_dir.rglob("*") if p.is_file() and is_image_file(p))[:limit]


def _read_for_ocr(image_path: Path, upscale: float):
    if upscale <= 1.0:
        return str(image_path)

    gray = cv2.imread(str(image_path), cv2.IMREAD_GRAYSCALE)
    if gray is None:
        return str(image_path)

    return cv2.resize(
        gray,
        None,
        fx=upscale,
        fy=upscale,
        interpolation=cv2.INTER_CUBIC,
    )


def run_ocr(input_dir: Path, input_file: Path | None, min_chars: int, language: str, limit: int, upscale: float, beamsearch: bool):
    image_paths = _collect_image_paths(input_dir, input_file, limit)
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
            ocr_input = _read_for_ocr(image_path, upscale)
            lines = reader.readtext(
                ocr_input,
                detail=0,
                paragraph=False,
                decoder="beamsearch" if beamsearch else "greedy",
            )
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
        args.input_file,
        args.min_chars,
        args.lang,
        args.limit,
        args.upscale,
        args.beamsearch,
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
