#!/usr/bin/env python3
import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


OUT_DIR = Path("artifacts/showcase_runs/latest/lcapy_test")
PNG_PATH = OUT_DIR / "lcapy_rc_test.png"
REPORT_PATH = OUT_DIR / "lcapy_test_report.md"
LATEX_SMOKE_DIR = OUT_DIR / "latex_smoke"
LATEX_SMOKE_TEX = LATEX_SMOKE_DIR / "circuitikz_smoke.tex"
LATEX_SMOKE_PDF = LATEX_SMOKE_DIR / "circuitikz_smoke.pdf"
MAC_TEXBIN = "/Library/TeX/texbin"


def _ensure_tex_path() -> None:
    path_parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    if Path(MAC_TEXBIN).exists() and MAC_TEXBIN not in path_parts:
        os.environ["PATH"] = os.pathsep.join([MAC_TEXBIN] + path_parts)


def _trim_output(value: str, limit: int = 4000) -> str:
    value = (value or "").strip()
    if len(value) <= limit:
        return value
    return value[-limit:]


def _latex_status() -> dict:
    _ensure_tex_path()
    status = {
        "pdflatex": shutil.which("pdflatex") or "",
        "latex": shutil.which("latex") or "",
        "kpsewhich": shutil.which("kpsewhich") or "",
        "tlmgr": shutil.which("tlmgr") or "",
        "circuitikz_status": "not_checked",
        "circuitikz_path": "",
        "circuitikz_probe_stderr": "",
    }
    if status["kpsewhich"]:
        try:
            probe = subprocess.run(
                [status["kpsewhich"], "circuitikz.sty"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
            status["circuitikz_probe_stderr"] = _trim_output(probe.stderr)
            if probe.returncode == 0 and probe.stdout.strip():
                status["circuitikz_status"] = "found"
                status["circuitikz_path"] = probe.stdout.strip()
            else:
                status["circuitikz_status"] = "not_found"
        except Exception as exc:
            status["circuitikz_status"] = "check_failed"
            status["circuitikz_probe_stderr"] = str(exc)
    return status


def _tlmgr_command(latex: dict) -> str:
    return f"{latex.get('tlmgr') or 'tlmgr'} install circuitikz"


def _run_latex_smoke(latex: dict) -> dict:
    if not latex.get("pdflatex"):
        return {
            "status": "SKIP",
            "detail": "pdflatex is missing; cannot run minimal circuitikz smoke test.",
            "stdout": "",
            "stderr": "",
        }

    LATEX_SMOKE_DIR.mkdir(parents=True, exist_ok=True)
    LATEX_SMOKE_TEX.write_text(
        "\n".join(
            [
                r"\documentclass{article}",
                r"\usepackage{circuitikz}",
                r"\pagestyle{empty}",
                r"\begin{document}",
                r"\begin{circuitikz}",
                r"\draw (0,0) to[R=$1\,\mathrm{k}\Omega$] (2,0) to[C=$1\,\mu\mathrm{F}$] (2,-2) -- (0,-2) -- (0,0);",
                r"\end{circuitikz}",
                r"\end{document}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    run = subprocess.run(
        [latex["pdflatex"], "-interaction=nonstopmode", "-halt-on-error", LATEX_SMOKE_TEX.name],
        cwd=LATEX_SMOKE_DIR,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if run.returncode == 0 and LATEX_SMOKE_PDF.exists() and LATEX_SMOKE_PDF.stat().st_size > 0:
        status = "PASS"
        detail = "minimal pdflatex circuitikz smoke test produced a PDF."
    else:
        status = "FAIL"
        detail = "minimal pdflatex circuitikz smoke test did not produce a PDF."
    return {
        "status": status,
        "detail": detail,
        "stdout": _trim_output(run.stdout),
        "stderr": _trim_output(run.stderr),
    }


def _write_report(
    status: str,
    detail: str,
    latex: dict,
    latex_smoke: dict | None = None,
    lcapy_stderr: str = "",
) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    latex_smoke = latex_smoke or {}
    lines = [
        "# Lcapy Schematic Test",
        "",
        f"- Status: {status}",
        f"- lcapy installed: {importlib.util.find_spec('lcapy') is not None}",
        f"- pdflatex: `{latex.get('pdflatex') or 'missing'}`",
        f"- latex: `{latex.get('latex') or 'missing'}`",
        f"- kpsewhich: `{latex.get('kpsewhich') or 'missing'}`",
        f"- circuitikz_status: `{latex.get('circuitikz_status')}`",
        f"- circuitikz_path: `{latex.get('circuitikz_path') or 'missing'}`",
        f"- circuitikz install command: `{_tlmgr_command(latex)}`",
        f"- direct LaTeX smoke: `{latex_smoke.get('status', 'not_run')}`",
        f"- Output image: `{PNG_PATH}`",
        f"- Direct LaTeX PDF: `{LATEX_SMOKE_PDF}`",
        "",
        "## Detail",
        "",
        detail,
    ]
    if latex_smoke:
        lines.extend(["", "## Direct LaTeX Circuitikz Smoke", "", latex_smoke.get("detail", "")])
        if latex_smoke.get("stderr"):
            lines.extend(["", "### pdflatex stderr", "", "```", latex_smoke["stderr"], "```"])
        if latex_smoke.get("stdout"):
            lines.extend(["", "### pdflatex stdout", "", "```", latex_smoke["stdout"], "```"])
    if lcapy_stderr:
        lines.extend(["", "## Lcapy/pdflatex stderr", "", "```", lcapy_stderr, "```"])
    if latex.get("circuitikz_probe_stderr"):
        lines.extend(["", "## kpsewhich stderr", "", "```", latex["circuitikz_probe_stderr"], "```"])
    lines.extend(["", "If this reports FAIL, the showcase still uses the fallback schematic renderer."])
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    latex = _latex_status()
    print(f"pdflatex={latex.get('pdflatex') or 'missing'}")
    print(f"kpsewhich={latex.get('kpsewhich') or 'missing'}")
    print(f"circuitikz_status={latex.get('circuitikz_status')}")
    if latex.get("circuitikz_path"):
        print(f"circuitikz_path={latex['circuitikz_path']}")
    if latex.get("circuitikz_status") != "found":
        print(f"Install circuitikz with: {_tlmgr_command(latex)}")

    latex_smoke = _run_latex_smoke(latex)
    print(f"direct_latex_smoke={latex_smoke['status']}: {latex_smoke['detail']}")
    if latex_smoke["status"] == "FAIL":
        if latex_smoke.get("stderr"):
            print("pdflatex stderr:")
            print(latex_smoke["stderr"])
        if latex_smoke.get("stdout"):
            print("pdflatex stdout:")
            print(latex_smoke["stdout"])

    if importlib.util.find_spec("lcapy") is None:
        detail = "FALLBACK: python package `lcapy` is not installed; the showcase will use the fallback schematic renderer."
        _write_report("FALLBACK", detail, latex, latex_smoke=latex_smoke)
        print(detail)
        print(f"Report: {REPORT_PATH}")
        return 0

    try:
        _ensure_tex_path()
        from lcapy import Circuit

        netlist = """
Vin in 0 ac 1
R1 in out 15.9k
C1 out 0 10n
"""
        circuit = Circuit(netlist)
        circuit.draw(str(PNG_PATH))
        if PNG_PATH.exists() and PNG_PATH.stat().st_size > 0:
            detail = "PASS: Lcapy rendered a simple RC schematic image."
            _write_report("PASS", detail, latex, latex_smoke=latex_smoke)
            print(detail)
            print(f"Image: {PNG_PATH}")
            return 0
        detail = "FALLBACK: Lcapy completed without producing a non-empty PNG; the showcase will use the fallback schematic renderer."
        _write_report("FALLBACK", detail, latex, latex_smoke=latex_smoke)
        print(detail)
        print(f"Report: {REPORT_PATH}")
        return 0
    except Exception as exc:
        stderr = _trim_output(getattr(exc, "stderr", "") or getattr(exc, "output", "") or "")
        detail = f"FALLBACK: Lcapy render failed: {exc}; the showcase will use the fallback schematic renderer."
        _write_report("FALLBACK", detail, latex, latex_smoke=latex_smoke, lcapy_stderr=stderr)
        print(detail)
        if stderr:
            print("Lcapy/pdflatex stderr:")
            print(stderr)
        print(f"Report: {REPORT_PATH}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
