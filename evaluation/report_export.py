import argparse
import csv
import json
import math
import os
from datetime import datetime
from pathlib import Path


def pass_at_k(total_samples: int, successful_samples: int, k: int) -> float:
    n = max(0, int(total_samples))
    c = max(0, min(int(successful_samples), n))
    k = max(1, int(k))
    if n == 0:
        return 0.0
    if c == 0:
        return 0.0
    if n - c < k:
        return 1.0
    return 1.0 - (math.comb(n - c, k) / math.comb(n, k))


def _safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def _mean(values):
    parsed = []
    for value in values:
        numeric = _safe_float(value)
        if numeric is not None:
            parsed.append(numeric)
    if not parsed:
        return None
    return sum(parsed) / len(parsed)


def _parse_ks(raw: str):
    values = []
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(max(1, int(part)))
        except Exception:
            continue
    return values or [1, 3, 5]


def _flatten_samples(samples):
    if isinstance(samples, list):
        return [item for item in samples if isinstance(item, dict)]
    if isinstance(samples, dict):
        merged = []
        for _, value in samples.items():
            if isinstance(value, list):
                merged.extend(item for item in value if isinstance(item, dict))
        return merged
    return []


def _pass_at_k_from_payload(overall: dict, total_samples: int, successful_samples: int, k: int):
    pass_at_k_dict = overall.get("pass_at_k") or {}
    keys = (f"k={k}", f"pass_at_{k}", str(k), f"pass@{k}")
    for key in keys:
        value = _safe_float(pass_at_k_dict.get(key))
        if value is not None:
            return value
    if total_samples <= 0:
        return None
    return pass_at_k(total_samples, successful_samples, k)


def _resolve_json_path(path: str):
    candidate = Path(path).expanduser()
    if candidate.is_dir():
        candidate = candidate / "benchmark_summary.json"
    if not candidate.exists():
        raise FileNotFoundError(f"Could not find benchmark JSON at '{path}'.")
    return candidate.resolve()


def _load_json(path: str):
    resolved = _resolve_json_path(path)
    with open(resolved, "r") as handle:
        payload = json.load(handle)
    return resolved, payload


def normalize_framework_result(framework: str, payload: dict, ks: list, source: str = ""):
    overall = payload.get("overall") or {}
    case_summaries = payload.get("case_summaries") or []
    samples = _flatten_samples(payload.get("samples") or {})

    total_cases = int(overall.get("total_cases") or len(case_summaries) or 0)
    total_samples = int(
        overall.get("total_samples")
        or sum(int(item.get("num_samples", 0)) for item in case_summaries)
        or len(samples)
    )
    successful_samples = int(
        overall.get("successful_samples")
        or sum(int(item.get("successful_samples", 0)) for item in case_summaries)
        or sum(1 for item in samples if item.get("success") is True)
    )
    sample_success_rate = _safe_float(overall.get("sample_success_rate"))
    if sample_success_rate is None and total_samples > 0:
        sample_success_rate = successful_samples / total_samples

    avg_case_runtime_s = _safe_float(overall.get("avg_case_runtime_s"))
    if avg_case_runtime_s is None:
        avg_case_runtime_s = _mean(item.get("avg_runtime_s") for item in case_summaries)

    avg_case_iterations = _mean(item.get("avg_iterations") for item in case_summaries)
    avg_verification_pass_rate = _mean(item.get("avg_verification_pass_rate") for item in case_summaries)
    avg_verification_coverage = _mean(item.get("avg_verification_coverage") for item in case_summaries)
    avg_topology_match_rate = _mean(item.get("topology_match_rate") for item in case_summaries)
    first_pass_success_rate = _safe_float(overall.get("first_pass_success_rate"))
    if first_pass_success_rate is None:
        first_pass_success_rate = _mean(item.get("first_pass_success_rate") for item in case_summaries)

    if avg_verification_pass_rate is None:
        avg_verification_pass_rate = _mean(
            (item.get("verification") or {}).get("pass_rate_on_known")
            for item in samples
        )
    if avg_verification_coverage is None:
        avg_verification_coverage = _mean(
            (item.get("verification") or {}).get("coverage_ratio")
            for item in samples
        )

    avg_llm_calls_per_sample = _mean(item.get("llm_call_count") for item in samples)
    avg_llm_success_rate = _safe_float(overall.get("avg_llm_success_rate"))
    if avg_llm_success_rate is None:
        avg_llm_success_rate = _mean(item.get("avg_llm_success_rate") for item in case_summaries)
    if avg_llm_success_rate is None:
        avg_llm_success_rate = _mean(item.get("llm_call_success_rate") for item in samples)

    composite_stage_count_match_rate = _safe_float(overall.get("composite_stage_count_match_rate"))
    if composite_stage_count_match_rate is None:
        composite_stage_count_match_rate = _mean(
            item.get("composite_stage_count_match_rate") for item in case_summaries
        )
    if composite_stage_count_match_rate is None:
        composite_stage_count_match_rate = _mean(
            1.0 if (item.get("composite") or {}).get("stage_count_match") is True else None
            for item in samples
        )

    composite_stage_order_match_rate = _safe_float(overall.get("composite_stage_order_match_rate"))
    if composite_stage_order_match_rate is None:
        composite_stage_order_match_rate = _mean(
            item.get("composite_stage_order_match_rate") for item in case_summaries
        )
    if composite_stage_order_match_rate is None:
        composite_stage_order_match_rate = _mean(
            1.0 if (item.get("composite") or {}).get("topology_order_match") is True else None
            for item in samples
        )

    row = {
        "framework": framework,
        "source": source,
        "total_cases": total_cases,
        "total_samples": total_samples,
        "successful_samples": successful_samples,
        "sample_success_rate": sample_success_rate,
        "first_pass_success_rate": first_pass_success_rate,
        "avg_case_runtime_s": avg_case_runtime_s,
        "avg_case_iterations": avg_case_iterations,
        "avg_verification_pass_rate": avg_verification_pass_rate,
        "avg_verification_coverage": avg_verification_coverage,
        "avg_topology_match_rate": avg_topology_match_rate,
        "avg_llm_calls_per_sample": avg_llm_calls_per_sample,
        "avg_llm_success_rate": avg_llm_success_rate,
        "composite_stage_count_match_rate": composite_stage_count_match_rate,
        "composite_stage_order_match_rate": composite_stage_order_match_rate,
    }
    for k in ks:
        row[f"pass_at_{k}"] = _pass_at_k_from_payload(
            overall=overall,
            total_samples=total_samples,
            successful_samples=successful_samples,
            k=k,
        )
    return row


def _csv_columns(ks: list):
    return [
        "framework",
        "source",
        "total_cases",
        "total_samples",
        "successful_samples",
        "sample_success_rate",
        "first_pass_success_rate",
        *[f"pass_at_{k}" for k in ks],
        "avg_case_runtime_s",
        "avg_case_iterations",
        "avg_verification_pass_rate",
        "avg_verification_coverage",
        "avg_topology_match_rate",
        "avg_llm_calls_per_sample",
        "avg_llm_success_rate",
        "composite_stage_count_match_rate",
        "composite_stage_order_match_rate",
    ]


def _format_float(value, digits=4):
    numeric = _safe_float(value)
    if numeric is None:
        return ""
    return f"{numeric:.{digits}f}"


def write_csv_table(rows: list, out_path: Path, ks: list):
    columns = _csv_columns(ks)
    with open(out_path, "w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        for row in rows:
            normalized = {}
            for key in columns:
                value = row.get(key)
                if key in {"framework", "source"}:
                    normalized[key] = value
                elif key in {"total_cases", "total_samples", "successful_samples"}:
                    normalized[key] = "" if value is None else int(value)
                else:
                    normalized[key] = _format_float(value, digits=6)
            writer.writerow(normalized)


def _latex_escape(text: str):
    value = str(text or "")
    return (
        value.replace("\\", "\\textbackslash{}")
        .replace("&", "\\&")
        .replace("%", "\\%")
        .replace("_", "\\_")
        .replace("#", "\\#")
        .replace("{", "\\{")
        .replace("}", "\\}")
        .replace("$", "\\$")
        .replace("~", "\\textasciitilde{}")
        .replace("^", "\\textasciicircum{}")
    )


def _fmt_latex_percent(value):
    numeric = _safe_float(value)
    if numeric is None:
        return "--"
    return f"{100.0 * numeric:.1f}\\%"


def _fmt_latex_float(value, digits=2):
    numeric = _safe_float(value)
    if numeric is None:
        return "--"
    return f"{numeric:.{digits}f}"


def write_latex_table(
    rows: list,
    out_path: Path,
    ks: list,
    caption: str = "Framework comparison under a shared benchmark metric schema.",
    label: str = "tab:framework_comparison",
):
    col_spec = "l" + "r" * (13 + len(ks))
    headers = [
        "Framework",
        "Cases",
        "Samples",
        "Success",
        "First-Pass",
        *[f"pass@{k}" for k in ks],
        "Runtime (s)",
        "Iter",
        "Verif Pass",
        "Verif Cov",
        "Topo Match",
        "LLM Calls",
        "LLM OK",
        "Stage Cnt",
        "Stage Ord",
    ]

    lines = [
        "\\begin{table*}[t]",
        "\\centering",
        f"\\caption{{{_latex_escape(caption)}}}",
        f"\\label{{{_latex_escape(label)}}}",
        "\\small",
        f"\\begin{{tabular}}{{{col_spec}}}",
        "\\toprule",
        " & ".join(headers) + " \\\\",
        "\\midrule",
    ]

    for row in rows:
        cells = [
            _latex_escape(row.get("framework")),
            str(int(row.get("total_cases") or 0)),
            str(int(row.get("total_samples") or 0)),
            _fmt_latex_percent(row.get("sample_success_rate")),
            _fmt_latex_percent(row.get("first_pass_success_rate")),
            *[_fmt_latex_percent(row.get(f"pass_at_{k}")) for k in ks],
            _fmt_latex_float(row.get("avg_case_runtime_s"), digits=2),
            _fmt_latex_float(row.get("avg_case_iterations"), digits=2),
            _fmt_latex_percent(row.get("avg_verification_pass_rate")),
            _fmt_latex_percent(row.get("avg_verification_coverage")),
            _fmt_latex_percent(row.get("avg_topology_match_rate")),
            _fmt_latex_float(row.get("avg_llm_calls_per_sample"), digits=2),
            _fmt_latex_percent(row.get("avg_llm_success_rate")),
            _fmt_latex_percent(row.get("composite_stage_count_match_rate")),
            _fmt_latex_percent(row.get("composite_stage_order_match_rate")),
        ]
        lines.append(" & ".join(cells) + " \\\\")

    lines.extend([
        "\\bottomrule",
        "\\end{tabular}",
        "\\end{table*}",
    ])

    with open(out_path, "w") as handle:
        handle.write("\n".join(lines) + "\n")


def export_comparison(framework_specs: list, out_dir: str, ks: list, caption: str, label: str):
    rows = []
    for framework_name, path in framework_specs:
        resolved, payload = _load_json(path)
        row = normalize_framework_result(
            framework=framework_name,
            payload=payload,
            ks=ks,
            source=str(resolved),
        )
        rows.append(row)

    rows.sort(key=lambda item: (_safe_float(item.get("sample_success_rate")) or 0.0), reverse=True)

    output_root = Path(out_dir).expanduser()
    output_root.mkdir(parents=True, exist_ok=True)

    csv_path = output_root / "framework_comparison.csv"
    tex_path = output_root / "framework_comparison.tex"
    schema_path = output_root / "comparison_schema.json"

    write_csv_table(rows=rows, out_path=csv_path, ks=ks)
    write_latex_table(rows=rows, out_path=tex_path, ks=ks, caption=caption, label=label)

    with open(schema_path, "w") as handle:
        json.dump(
            {
                "columns": _csv_columns(ks),
                "ks": ks,
                "frameworks": [row.get("framework") for row in rows],
            },
            handle,
            indent=2,
        )

    return {
        "csv": str(csv_path),
        "latex": str(tex_path),
        "schema": str(schema_path),
    }


def _parse_framework_specs(raw_specs: list):
    parsed = []
    for raw in raw_specs:
        if "=" in raw:
            name, path = raw.split("=", 1)
            parsed.append((name.strip(), path.strip()))
            continue
        path = raw.strip()
        name = Path(path).stem or "framework"
        parsed.append((name, path))
    if not parsed:
        raise ValueError("At least one --framework entry is required.")
    return parsed


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Export a single paper-ready CSV and LaTeX table comparing frameworks "
            "on a shared benchmark metric schema."
        )
    )
    parser.add_argument(
        "--framework",
        action="append",
        required=True,
        help=(
            "Framework input in the form name=/path/to/benchmark_summary.json. "
            "You can also pass just a path and name will be auto-derived."
        ),
    )
    parser.add_argument(
        "--out-dir",
        default=os.path.join(
            "artifacts",
            "reports",
            datetime.now().strftime("%Y%m%d_%H%M%S_framework_comparison"),
        ),
        help="Output directory for CSV/LaTeX/schema files.",
    )
    parser.add_argument("--ks", default="1,3,5", help="Comma-separated pass@k values to include (default: 1,3,5).")
    parser.add_argument(
        "--caption",
        default="Framework comparison under a shared benchmark metric schema.",
        help="LaTeX table caption.",
    )
    parser.add_argument(
        "--label",
        default="tab:framework_comparison",
        help="LaTeX table label.",
    )
    args = parser.parse_args()

    framework_specs = _parse_framework_specs(args.framework)
    ks = _parse_ks(args.ks)
    outputs = export_comparison(
        framework_specs=framework_specs,
        out_dir=args.out_dir,
        ks=ks,
        caption=args.caption,
        label=args.label,
    )
    print(f"Wrote CSV: {outputs['csv']}")
    print(f"Wrote LaTeX: {outputs['latex']}")
    print(f"Wrote schema: {outputs['schema']}")


if __name__ == "__main__":
    main()
