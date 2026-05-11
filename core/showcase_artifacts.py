import csv
import html
import json
import os
import re
import shutil
from datetime import datetime
from pathlib import Path


LATEST_ROOT = Path("artifacts/showcase_runs/latest")
PRESERVED_LATEST_DIRS = {"hf_backend_test", "lcapy_test"}


TYPE_TO_DIR = {
    "netlist": "netlists",
    "netlist_prompt": "netlists",
    "raw_llm_response": "netlists",
    "netlist_backend_metadata": "netlists",
    "schematic": "schematics",
    "ac_plot": "plots",
    "dc_plot": "plots",
    "transient_plot": "plots",
    "comparison_table": "sweeps",
    "comparison_plot": "plots",
    "comparison_summary": "sweeps",
    "report": "reports",
    "metrics": "reports",
}


def reset_latest_root(root: Path = LATEST_ROOT) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    for child in root.iterdir():
        if child.is_dir() and child.name in PRESERVED_LATEST_DIRS:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except FileNotFoundError:
                pass
    for name in ("cases", "sweeps", "schematics", "netlists", "plots", "reports"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return root


def organize_showcase_latest(
    *,
    command: str,
    case_rows: list[dict] = None,
    sweep_groups: list[dict] = None,
    architecture_summary: str = "",
    root: Path = LATEST_ROOT,
    clean: bool = True,
) -> dict:
    if clean:
        reset_latest_root(root)
    else:
        root.mkdir(parents=True, exist_ok=True)
        for name in ("cases", "sweeps", "schematics", "netlists", "plots", "reports"):
            (root / name).mkdir(parents=True, exist_ok=True)

    case_rows = list(case_rows or [])
    sweep_groups = list(sweep_groups or [])
    manifest = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "command": command,
        "root": str(root),
        "artifacts": [],
    }

    for row in case_rows:
        _collect_row_artifacts(root, manifest, row, sweep_name=None)

    for group in sweep_groups:
        sweep_name = group.get("name") or "sweep"
        sweep_dir = root / "sweeps" / _slug(sweep_name)
        sweep_dir.mkdir(parents=True, exist_ok=True)
        for src, artifact_type in (
            (group.get("comparison_summary"), "comparison_summary"),
            (group.get("comparison_table"), "comparison_table"),
            (group.get("comparison_plot"), "comparison_plot"),
        ):
            _add_artifact(
                root,
                manifest,
                src,
                artifact_type,
                case_name=sweep_name,
                sweep_value=None,
                label=_slug(sweep_name),
                backend_used=group.get("backend_used"),
                simulator_status=group.get("simulator_status"),
                final_verdict=group.get("final_verdict"),
                preferred_dir=sweep_dir if artifact_type != "comparison_plot" else None,
            )
        for row in group.get("rows") or []:
            _collect_row_artifacts(root, manifest, row, sweep_name=sweep_name)

    _write_manifest(root, manifest)
    _write_case_pages(root, manifest, case_rows, sweep_groups)
    _write_summary(root, manifest, case_rows, sweep_groups, command, architecture_summary)
    _write_index_html(root)
    return manifest


def load_showcase_manifest(path: Path = None) -> dict:
    path = Path(path or (LATEST_ROOT / "artifact_manifest.json"))
    if not path.exists():
        return {"artifacts": []}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"artifacts": []}


def artifacts_for_row(
    manifest: dict,
    case_name: str,
    sweep_parameter=None,
    sweep_value=None,
    *,
    require_exists: bool = True,
) -> dict:
    label = _artifact_label(case_name, sweep_parameter, sweep_value)
    out = {}
    for item in (manifest or {}).get("artifacts") or []:
        item_label = _artifact_label(
            item.get("case_name"),
            item.get("parameter_sweep_name"),
            item.get("parameter_sweep_value"),
        )
        if item_label != label:
            continue
        path = item.get("showcase_copy_path") or item.get("source_artifact_path")
        if not path:
            continue
        if require_exists and not Path(path).exists():
            continue
        out.setdefault(item.get("type") or "artifact", []).append(path)
    return out


def row_from_final_state(case_name: str, final_state: dict, sweep_parameter=None, sweep_value=None) -> dict:
    sim = final_state.get("simulation_results") or {}
    verification = sim.get("verification_summary") or {}
    backend = sim.get("netlist_backend_metadata") or final_state.get("netlist_backend_metadata") or {}
    artifact_dir = sim.get("artifact_dir") or ""
    return {
        "case": case_name,
        "sweep_parameter": sweep_parameter,
        "requested_spec": sweep_value,
        "artifact_dir": artifact_dir,
        "generated_netlist": sim.get("saved_netlist_path") or "",
        "netlist_prompt": backend.get("prompt_sent_path") or (str(Path(artifact_dir) / "netlist_prompt.txt") if artifact_dir else ""),
        "raw_llm_response": backend.get("raw_llm_response_path") or (str(Path(artifact_dir) / "raw_llm_response.txt") if artifact_dir else ""),
        "netlist_backend_metadata": backend.get("metadata_path") or (str(Path(artifact_dir) / "netlist_backend_metadata.json") if artifact_dir else ""),
        "schematic_png": sim.get("schematic_png_path") or "",
        "schematic_svg": sim.get("schematic_svg_path") or "",
        "ac_plot": sim.get("ac_plot") or "",
        "dc_plot": sim.get("dc_plot") or "",
        "tran_plot": sim.get("tran_plot") or "",
        "final_report": str(Path(artifact_dir) / "final_report.txt") if artifact_dir else "",
        "metrics": str(Path(artifact_dir) / "metrics_summary.json") if artifact_dir else "",
        "backend_used": backend.get("backend_used") or "",
        "simulator_status": _simulator_status(final_state),
        "final_verdict": verification.get("overall_verdict") or final_state.get("status") or "",
    }


def sweep_group_from_output(name: str, output_dir: str, rows: list[dict]) -> dict:
    output = Path(output_dir)
    enriched = []
    for row in rows:
        value = row.get("requested_spec")
        enriched.append(
            {
                **row,
                "netlist_prompt": _sibling(row.get("generated_netlist"), "netlist_prompt.txt"),
                "raw_llm_response": _sibling(row.get("generated_netlist"), "raw_llm_response.txt"),
                "netlist_backend_metadata": _sibling(row.get("generated_netlist"), "netlist_backend_metadata.json"),
                "schematic_svg": _with_suffix(row.get("schematic_png"), ".svg"),
                "metrics": _sibling(row.get("final_report"), "metrics_summary.json"),
                "simulator_status": "SIMULATION MISSING" if row.get("pass_fail") == "SIMULATION MISSING" else "COMPLETE",
                "final_verdict": row.get("pass_fail") or "",
                "sweep_parameter": row.get("sweep_parameter"),
                "requested_spec": value,
            }
        )
    return {
        "name": name,
        "rows": enriched,
        "comparison_summary": str(output / "comparison_summary.md"),
        "comparison_table": str(output / "comparison_table.csv"),
        "comparison_plot": str(output / "comparison_plot.png"),
    }


def _collect_row_artifacts(root: Path, manifest: dict, row: dict, sweep_name=None):
    case_name = row.get("case") or sweep_name or "case"
    sweep_value = row.get("requested_spec")
    sweep_parameter = row.get("sweep_parameter")
    label = _artifact_label(case_name, row.get("sweep_parameter"), sweep_value)
    for src, artifact_type in (
        (row.get("generated_netlist"), "netlist"),
        (row.get("netlist_prompt"), "netlist_prompt"),
        (row.get("raw_llm_response"), "raw_llm_response"),
        (row.get("netlist_backend_metadata"), "netlist_backend_metadata"),
        (row.get("schematic_png"), "schematic"),
        (row.get("schematic_svg"), "schematic"),
        (row.get("ac_plot"), "ac_plot"),
        (row.get("dc_plot"), "dc_plot"),
        (row.get("tran_plot"), "transient_plot"),
        (row.get("final_report"), "report"),
        (row.get("metrics"), "metrics"),
    ):
        _add_artifact(
            root,
            manifest,
            src,
            artifact_type,
            case_name=case_name,
            sweep_value=sweep_value,
            sweep_parameter=sweep_parameter,
            label=label,
            backend_used=row.get("backend_used"),
            simulator_status=row.get("simulator_status"),
            final_verdict=row.get("final_verdict") or row.get("pass_fail"),
        )


def _add_artifact(
    root: Path,
    manifest: dict,
    source,
    artifact_type: str,
    *,
    case_name,
    sweep_value,
    label,
    sweep_parameter=None,
    backend_used=None,
    simulator_status=None,
    final_verdict=None,
    preferred_dir: Path = None,
):
    if not source:
        return
    src = Path(str(source))
    if not src.exists() or not src.is_file():
        return
    bucket = TYPE_TO_DIR.get(artifact_type, "reports")
    dest_dir = preferred_dir or (root / bucket)
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix or ".txt"
    dest_name = _dest_name(label, artifact_type, suffix)
    dest = dest_dir / dest_name
    if src.resolve() != dest.resolve():
        shutil.copy2(src, dest)
    manifest["artifacts"].append(
        {
            "case_name": case_name,
            "parameter_sweep_value": sweep_value,
            "parameter_sweep_name": sweep_parameter,
            "source_artifact_path": str(src),
            "showcase_copy_path": str(dest),
            "type": artifact_type,
            "backend_used": backend_used or "",
            "simulator_status": simulator_status or "",
            "final_verdict": final_verdict or "",
        }
    )


def _dest_name(label: str, artifact_type: str, suffix: str) -> str:
    names = {
        "netlist": f"{label}_generated.sp",
        "netlist_prompt": f"{label}_netlist_prompt.txt",
        "raw_llm_response": f"{label}_raw_llm_response.txt",
        "netlist_backend_metadata": f"{label}_netlist_backend_metadata.json",
        "schematic": f"{label}_schematic{suffix}",
        "ac_plot": f"{label}_ac_plot{suffix}",
        "dc_plot": f"{label}_dc_plot{suffix}",
        "transient_plot": f"{label}_tran_plot{suffix}",
        "report": f"{label}_final_report.txt",
        "metrics": f"{label}_metrics_summary.json",
        "comparison_table": f"{label}_comparison_table.csv",
        "comparison_plot": f"{label}_comparison_plot{suffix}",
        "comparison_summary": f"{label}_comparison_summary.md",
    }
    return names.get(artifact_type, f"{label}_{artifact_type}{suffix}")


def _write_manifest(root: Path, manifest: dict):
    (root / "artifact_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")


def _write_summary(root: Path, manifest: dict, case_rows: list[dict], sweep_groups: list[dict], command: str, architecture_summary: str):
    lines = [
        "# I13 Analog Design Showcase",
        "",
        f"Exact command used: `{command}`",
        "",
        "## System Architecture",
        "",
        architecture_summary or (
            "Topology, sizing, netlist, operating-point, simulation, constraint, and refinement agents share a design state. "
            "LLM backends are optional for interpretation and synthesis; deterministic equations, ngspice, metric extraction, and verification provide the evidence path."
        ),
        "",
        "## Final Verdict Table",
        "",
        "| case | sweep value | verdict | simulator | backend | report | netlist | schematic | plots |",
        "|---|---:|---|---|---|---|---|---|---|",
    ]
    row_keys = _row_link_map(manifest)
    for row in _summary_rows(case_rows, sweep_groups):
        label = _artifact_label(row.get("case"), row.get("sweep_parameter"), row.get("requested_spec"))
        links = row_keys.get(label, {})
        plot_links = ", ".join(filter(None, [links.get("ac_plot"), links.get("dc_plot"), links.get("transient_plot")])) or "n/a"
        lines.append(
            f"| {row.get('case')} | {_fmt(row.get('requested_spec'))} | {row.get('final_verdict') or row.get('pass_fail') or 'n/a'} | "
            f"{row.get('simulator_status') or 'n/a'} | {row.get('backend_used') or 'n/a'} | "
            f"{links.get('report', 'n/a')} | {links.get('netlist', 'n/a')} | {links.get('schematic', 'n/a')} | {plot_links} |"
        )

    lines.extend(["", "## Cases Run", ""])
    if case_rows:
        for row in case_rows:
            lines.append(f"- `{row.get('case')}`: {row.get('final_verdict') or 'n/a'}")
    else:
        lines.append("- No standalone cases were run.")

    lines.extend(["", "## Parameter Sweeps Run", ""])
    if sweep_groups:
        for group in sweep_groups:
            comp = _manifest_link(manifest, group.get("comparison_table"), "comparison_table")
            plot = _manifest_link(manifest, group.get("comparison_plot"), "comparison_plot")
            lines.append(f"- `{group.get('name')}`: comparison table {comp or 'n/a'}, comparison plot {plot or 'n/a'}")
    else:
        lines.append("- No parameter sweeps were run.")

    lines.extend(
        [
            "",
            "## Parameter-Change Evidence",
            "",
            "Each sweep value regenerates sizing, `generated.sp`, schematic images, ngspice plots, extracted metrics, and a final report. "
            "The copied files in `netlists/`, `schematics/`, `plots/`, and `reports/` use parameterized names so two sweep points can be opened side by side during the showcase.",
            "",
            "## Key Folders",
            "",
            "- [netlists/](netlists/)",
            "- [schematics/](schematics/)",
            "- [plots/](plots/)",
            "- [reports/](reports/)",
            "- [artifact_manifest.json](artifact_manifest.json)",
        ]
    )
    (root / "summary.md").write_text("\n".join(lines) + "\n")


def _write_case_pages(root: Path, manifest: dict, case_rows: list[dict], sweep_groups: list[dict]):
    row_keys = _row_link_map(manifest)
    for row in case_rows or []:
        case = row.get("case") or "case"
        label = _artifact_label(case, row.get("sweep_parameter"), row.get("requested_spec"))
        case_dir = root / "cases" / _slug(case)
        case_dir.mkdir(parents=True, exist_ok=True)
        links = row_keys.get(label, {})
        _write_readme(
            case_dir / "README.md",
            title=f"Case: {case}",
            rows=[
                ("verdict", row.get("final_verdict")),
                ("simulator", row.get("simulator_status")),
                ("backend", row.get("backend_used")),
                ("report", links.get("report")),
                ("netlist", links.get("netlist")),
                ("schematic", links.get("schematic")),
                ("ac_plot", links.get("ac_plot")),
                ("dc_plot", links.get("dc_plot")),
                ("transient_plot", links.get("transient_plot")),
            ],
        )

    for group in sweep_groups or []:
        name = group.get("name") or "sweep"
        sweep_dir = root / "sweeps" / _slug(name)
        sweep_dir.mkdir(parents=True, exist_ok=True)
        lines = [f"# Sweep: {name}", ""]
        for row in group.get("rows") or []:
            label = _artifact_label(row.get("case"), row.get("sweep_parameter"), row.get("requested_spec"))
            links = row_keys.get(label, {})
            lines.append(f"## {row.get('case')} {row.get('sweep_parameter')}={_fmt(row.get('requested_spec'))}")
            for key in ("report", "netlist", "schematic", "ac_plot", "dc_plot", "transient_plot"):
                if links.get(key):
                    lines.append(f"- {key}: {links[key]}")
            lines.append("")
        (sweep_dir / "README.md").write_text("\n".join(lines) + "\n")


def _write_readme(path: Path, title: str, rows: list[tuple[str, str]]):
    lines = [f"# {title}", ""]
    for key, value in rows:
        if value:
            lines.append(f"- {key}: {value}")
    path.write_text("\n".join(lines) + "\n")


def _write_index_html(root: Path):
    manifest_path = root / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {"artifacts": []}
    cards = _html_artifact_cards(root, manifest)
    sweep_cards = _html_sweep_cards(root, manifest)
    generated_at = html.escape(str(manifest.get("generated_at") or ""))
    empty_case_cards = '<div class="empty">No case cards found yet. Run the showcase or UI to populate artifacts.</div>'
    empty_sweep_cards = '<div class="empty">No sweep artifacts found yet.</div>'
    (root / "index.html").write_text(
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<title>Multi-Agent LLM Analog Circuit Design Automation</title>"
        "<style>"
        ":root{--ink:#162033;--muted:#667085;--line:#d7dde8;--bg:#f4f7fb;--panel:#fff;--ok:#067647;--bad:#b42318;--warn:#b54708;--accent:#1456b8;--band:#e9eef7}"
        "body{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif;line-height:1.45}"
        "header{background:#111827;color:white;padding:34px 40px 28px}"
        "h1{margin:0 0 10px;font-size:34px;letter-spacing:0}h2{margin:28px 0 14px;font-size:21px}h3{margin:0 0 8px;font-size:17px}"
        "main{max-width:1220px;margin:0 auto;padding:26px 28px 46px}.lede{max-width:930px;color:#d7deea}"
        ".grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px}.card{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:16px;box-shadow:0 1px 2px rgba(16,24,40,.04)}"
        ".wide{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:18px;margin:18px 0}.steps{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:10px}.step{background:var(--band);border-radius:7px;padding:10px;font-size:13px;font-weight:650}"
        ".meta{font-size:13px;color:var(--muted)}.pill{display:inline-block;border-radius:999px;padding:3px 9px;font-size:12px;font-weight:700;margin-right:6px}.pass{background:#dcfae6;color:var(--ok)}.fail{background:#fee4e2;color:var(--bad)}.partial,.warn{background:#fef0c7;color:var(--warn)}.unknown{background:#eef2f6;color:#344054}"
        "img{max-width:100%;max-height:260px;object-fit:contain;border:1px solid var(--line);border-radius:7px;background:white;margin:8px 0}.thumbs{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}.links a{display:inline-block;margin:5px 9px 0 0;color:var(--accent);text-decoration:none}.links a:hover{text-decoration:underline}"
        "code{background:#eef2f7;padding:2px 5px;border-radius:4px}.hero-links a{color:white;margin-right:16px}.empty{color:var(--muted);background:white;border:1px dashed var(--line);padding:18px;border-radius:8px}"
        "@media(max-width:700px){header{padding:24px 18px}main{padding:18px}h1{font-size:27px}}"
        "</style></head><body>"
        "<header>"
        "<h1>Multi-Agent LLM Analog Circuit Design Automation</h1>"
        "<p class='lede'>Prompt to topology to sizing to SPICE netlist to ngspice simulation to schematic to verified report. Agents handle interpretation and design planning; deterministic equations, simulators, extractors, and fallbacks keep the public demo reliable offline.</p>"
        f"<div class='meta'>Generated: {generated_at}</div>"
        "<div class='hero-links'><a href='summary.md'>summary.md</a><a href='artifact_manifest.json'>artifact_manifest.json</a><a href='netlists/'>netlists/</a><a href='schematics/'>schematics/</a><a href='plots/'>plots/</a><a href='reports/'>reports/</a></div>"
        "</header><main>"
        "<section class='wide'><h2>How To Demo This</h2><div class='steps'>"
        "<div class='step'>1. Open the live UI with <code>streamlit run ui_showcase.py</code>.</div>"
        "<div class='step'>2. Paste a natural-language analog design request.</div>"
        "<div class='step'>3. Show parsed constraints, selected topology, and agent path.</div>"
        "<div class='step'>4. Open generated.sp, schematic, plots, and final_report.txt.</div>"
        "</div></section>"
        "<section class='wide'><h2>Safe Offline Demo vs Optional Hugging Face Demo</h2>"
        "<p>The safe path uses deterministic topology, sizing, netlist templates, ngspice checks, and fallback schematic rendering. The optional Hugging Face path may attempt cloud netlist generation, then records backend metadata and falls back deterministically if quota, network, or parsing fails. API keys are never printed by the artifact index.</p>"
        "</section>"
        "<section class='wide'><h2>Architecture</h2><p>Specification / Prompt -> TopologyAgent -> SizingAgent -> ConstraintAgent -> NetlistAgent -> OperatingPointAgent -> SimulationAgent -> RefinementAgent -> Artifact/Report Generator.</p></section>"
        "<h2>Cases</h2>"
        f"{cards or empty_case_cards}"
        "<h2>Parameter Sweeps</h2>"
        f"{sweep_cards or empty_sweep_cards}"
        "</main></body></html>\n"
    )


def _html_artifact_cards(root: Path, manifest: dict) -> str:
    groups = {}
    for item in manifest.get("artifacts") or []:
        if item.get("type") in {"comparison_table", "comparison_plot", "comparison_summary"}:
            continue
        label = _artifact_label(item.get("case_name"), item.get("parameter_sweep_name"), item.get("parameter_sweep_value"))
        group = groups.setdefault(
            label,
            {
                "case": item.get("case_name") or "case",
                "sweep_parameter": item.get("parameter_sweep_name"),
                "sweep_value": item.get("parameter_sweep_value"),
                "verdict": item.get("final_verdict") or "",
                "backend": item.get("backend_used") or "",
                "simulator": item.get("simulator_status") or "",
                "paths": {},
            },
        )
        group["paths"].setdefault(item.get("type"), []).append(item.get("showcase_copy_path"))
        for key in ("final_verdict", "backend_used", "simulator_status"):
            if item.get(key):
                target = {"final_verdict": "verdict", "backend_used": "backend", "simulator_status": "simulator"}[key]
                group[target] = item.get(key)

    cards = []
    for label, group in sorted(groups.items()):
        title = html.escape(str(group["case"]))
        if group.get("sweep_value") not in (None, ""):
            title += f" <span class='meta'>{html.escape(str(group.get('sweep_parameter') or 'value'))}={html.escape(_fmt(group.get('sweep_value')))}</span>"
        verdict = str(group.get("verdict") or "unknown")
        verdict_class = _verdict_class(verdict)
        metrics = _html_metrics_preview(group["paths"].get("metrics") or [])
        links = []
        for artifact_type, link_text in (
            ("netlist", "generated.sp"),
            ("report", "final_report.txt"),
            ("metrics", "metrics.json"),
            ("netlist_backend_metadata", "backend metadata"),
        ):
            for path in group["paths"].get(artifact_type) or []:
                rel = html.escape(os.path.relpath(path, root))
                links.append(f"<a href='{rel}'>{link_text}</a>")
                break
        images = []
        for artifact_type in ("schematic", "ac_plot", "dc_plot", "transient_plot"):
            for path in group["paths"].get(artifact_type) or []:
                suffix = Path(path).suffix.lower()
                if suffix in {".png", ".jpg", ".jpeg", ".svg"}:
                    rel = html.escape(os.path.relpath(path, root))
                    images.append(f"<img src='{rel}' alt='{html.escape(Path(path).name)}'>")
                    break
        cards.append(
            "<article class='card'>"
            f"<h3>{title}</h3>"
            f"<span class='pill {verdict_class}'>{html.escape(verdict or 'unknown')}</span>"
            f"<span class='pill unknown'>{html.escape(str(group.get('simulator') or 'simulator n/a'))}</span>"
            f"<p class='meta'>Backend: {html.escape(str(group.get('backend') or 'n/a'))}</p>"
            f"{metrics}"
            + "<div class='thumbs'>"
            + "".join(images[:4])
            + "</div>"
            + f"<div class='links'>{''.join(links)}</div>"
            "</article>"
        )
    return "<div class='grid'>" + "".join(cards) + "</div>" if cards else ""


def _html_metrics_preview(paths: list[str]) -> str:
    for path in paths:
        p = Path(path)
        if not p.exists() or p.suffix.lower() != ".json":
            continue
        try:
            data = json.loads(p.read_text())
        except Exception:
            continue
        measured = data.get("measured") or ((data.get("verification_summary") or {}).get("extracted_metrics") or {})
        if not measured:
            continue
        parts = []
        for key, value in list(measured.items())[:4]:
            if value is None:
                continue
            if isinstance(value, float):
                value = f"{value:.5g}"
            parts.append(f"<code>{html.escape(str(key))}={html.escape(str(value))}</code>")
        if parts:
            return "<p class='meta'>Key metrics: " + " ".join(parts) + "</p>"
    return ""


def _html_sweep_cards(root: Path, manifest: dict) -> str:
    groups = {}
    for item in manifest.get("artifacts") or []:
        if item.get("type") not in {"comparison_table", "comparison_plot", "comparison_summary"}:
            continue
        name = item.get("case_name") or "sweep"
        group = groups.setdefault(name, {"paths": {}})
        group["paths"].setdefault(item.get("type"), []).append(item.get("showcase_copy_path"))
    cards = []
    for name, group in sorted(groups.items()):
        links = []
        image = ""
        for artifact_type, link_text in (
            ("comparison_summary", "comparison summary"),
            ("comparison_table", "comparison table"),
        ):
            for path in group["paths"].get(artifact_type) or []:
                rel = html.escape(os.path.relpath(path, root))
                links.append(f"<a href='{rel}'>{link_text}</a>")
                break
        for path in group["paths"].get("comparison_plot") or []:
            if Path(path).suffix.lower() in {".png", ".jpg", ".jpeg", ".svg"}:
                rel = html.escape(os.path.relpath(path, root))
                image = f"<img src='{rel}' alt='{html.escape(Path(path).name)}'>"
                links.append(f"<a href='{rel}'>comparison plot</a>")
                break
        cards.append(
            "<article class='card'>"
            f"<h3>{html.escape(str(name))}</h3>"
            "<p class='meta'>Each point regenerates component values, generated.sp, schematic, plots, metrics, and report artifacts.</p>"
            f"{image}<div class='links'>{''.join(links)}</div>"
            "</article>"
        )
    return "<div class='grid'>" + "".join(cards) + "</div>" if cards else ""


def _verdict_class(verdict: str) -> str:
    lowered = (verdict or "").lower()
    if "partial" in lowered or "missing" in lowered or "warn" in lowered:
        return "partial"
    if "pass" in lowered or "verified" in lowered:
        return "pass"
    if "fail" in lowered or "invalid" in lowered:
        return "fail"
    return "unknown"


def _row_link_map(manifest: dict) -> dict:
    out = {}
    for item in manifest.get("artifacts") or []:
        label = _artifact_label(item.get("case_name"), item.get("parameter_sweep_name"), item.get("parameter_sweep_value"))
        path = Path(item["showcase_copy_path"])
        rel = os.path.relpath(path, LATEST_ROOT)
        link = f"[{path.name}]({rel})"
        bucket = out.setdefault(label, {})
        if item.get("type") == "schematic":
            if path.suffix.lower() == ".png" or "schematic" not in bucket:
                bucket["schematic"] = link
        else:
            bucket[item.get("type")] = link
    return out


def _manifest_link(manifest: dict, source, artifact_type):
    for item in manifest.get("artifacts") or []:
        if item.get("source_artifact_path") == str(source) and item.get("type") == artifact_type:
            path = Path(item["showcase_copy_path"])
            return f"[{path.name}]({os.path.relpath(path, LATEST_ROOT)})"
    return None


def _summary_rows(case_rows, sweep_groups):
    rows = list(case_rows or [])
    for group in sweep_groups or []:
        for row in group.get("rows") or []:
            rows.append(row)
    return rows


def _artifact_label(case_name, sweep_parameter=None, sweep_value=None):
    case_slug = _slug(case_name or "case")
    if sweep_value is None or sweep_value == "":
        return case_slug
    param = _short_param(sweep_parameter)
    return _slug(f"{case_slug}_{param}_{_fmt(sweep_value)}")


def _short_param(value):
    mapping = {
        "target_fc_hz": "target_fc",
        "target_gain_db": "target_gain",
        "load_cap_f": "load_cap",
        "target_iout_a": "target_iout",
    }
    return mapping.get(value or "value", value or "value")


def _slug(value):
    text = re.sub(r"[^a-zA-Z0-9]+", "_", str(value).strip().lower())
    return text.strip("_") or "item"


def _fmt(value):
    if value is None or value == "":
        return ""
    try:
        return f"{float(value):.6g}".replace("+", "")
    except Exception:
        return str(value)


def _sibling(path, filename):
    if not path:
        return ""
    return str(Path(path).parent / filename)


def _with_suffix(path, suffix):
    if not path:
        return ""
    return str(Path(path).with_suffix(suffix))


def _simulator_status(final_state: dict):
    sim = final_state.get("simulation_results") or {}
    if sim.get("simulation_skipped"):
        return "SIMULATION MISSING"
    if sim.get("returncode") == 0:
        return "COMPLETE"
    if sim.get("returncode") is None:
        return "NOT TESTED"
    return "FAILED"


_TYPE_TO_ROW_KEY = {
    "netlist": "generated_netlist",
    "netlist_prompt": "netlist_prompt",
    "raw_llm_response": "raw_llm_response",
    "netlist_backend_metadata": "netlist_backend_metadata",
    "ac_plot": "ac_plot",
    "dc_plot": "dc_plot",
    "transient_plot": "tran_plot",
    "report": "final_report",
    "metrics": "metrics",
}


def reconstruct_rows_from_manifest(manifest_path) -> tuple[list[dict], list[dict]]:
    """Read an existing showcase manifest and produce (case_rows, sweep_groups) suitable
    for re-feeding to organize_showcase_latest. Source artifact paths are used so the
    re-organize step copies fresh files from the underlying simulation directory.
    Missing source files are skipped gracefully."""
    path = Path(manifest_path)
    if not path.exists():
        return [], []
    try:
        manifest = json.loads(path.read_text())
    except Exception:
        return [], []
    case_buckets: dict[tuple, dict] = {}
    sweep_buckets: dict[str, dict] = {}
    sweep_row_buckets: dict[tuple, dict] = {}
    for item in manifest.get("artifacts") or []:
        source = item.get("source_artifact_path") or ""
        if not source or not Path(source).exists():
            source = item.get("showcase_copy_path") or ""
        if not source or not Path(source).exists():
            continue
        artifact_type = item.get("type")
        case_name = item.get("case_name") or "case"
        sweep_param = item.get("parameter_sweep_name")
        sweep_value = item.get("parameter_sweep_value")
        if artifact_type in {"comparison_summary", "comparison_table", "comparison_plot"}:
            group = sweep_buckets.setdefault(case_name, {"name": case_name, "rows": [], "comparison_summary": "", "comparison_table": "", "comparison_plot": ""})
            group[artifact_type] = source
            continue
        if sweep_param:
            row = sweep_row_buckets.setdefault(
                (case_name, sweep_param, sweep_value),
                {
                    "case": case_name,
                    "sweep_parameter": sweep_param,
                    "requested_spec": sweep_value,
                    "backend_used": item.get("backend_used") or "",
                    "simulator_status": item.get("simulator_status") or "",
                    "final_verdict": item.get("final_verdict") or "",
                },
            )
        else:
            row = case_buckets.setdefault(
                (case_name, sweep_param, sweep_value),
                {
                    "case": case_name,
                    "sweep_parameter": sweep_param,
                    "requested_spec": sweep_value,
                    "backend_used": item.get("backend_used") or "",
                    "simulator_status": item.get("simulator_status") or "",
                    "final_verdict": item.get("final_verdict") or "",
                },
            )
        if artifact_type == "schematic":
            suffix = Path(source).suffix.lower()
            if suffix == ".png":
                row["schematic_png"] = source
            elif suffix == ".svg":
                row["schematic_svg"] = source
            else:
                row.setdefault("schematic_png", source)
        else:
            key = _TYPE_TO_ROW_KEY.get(artifact_type)
            if key:
                row[key] = source
    case_rows = list(case_buckets.values())
    for (case_name, sweep_param, sweep_value), row in sweep_row_buckets.items():
        group = _match_sweep_group(sweep_buckets, case_name, sweep_param)
        if group is None:
            group = sweep_buckets.setdefault(
                case_name,
                {"name": case_name, "rows": [], "comparison_summary": "", "comparison_table": "", "comparison_plot": ""},
            )
        group["rows"].append(row)
    sweep_groups = list(sweep_buckets.values())
    return case_rows, sweep_groups


def _match_sweep_group(sweep_buckets: dict, case_name: str, sweep_param: str):
    expected = f"{case_name}_{sweep_param or ''}".strip("_").lower()
    for name, group in sweep_buckets.items():
        if (name or "").lower() == expected:
            return group
    for name, group in sweep_buckets.items():
        lowered = (name or "").lower()
        if (case_name or "").lower() in lowered and (sweep_param or "").lower() in lowered:
            return group
    for name, group in sweep_buckets.items():
        if (case_name or "").lower() in (name or "").lower():
            return group
    return None


def load_sweep_rows_csv(path: str) -> list[dict]:
    with open(path, newline="") as handle:
        return list(csv.DictReader(handle))
