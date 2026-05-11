import importlib.util
import os
import platform
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import List, Tuple

from core.runtime_backend import resolve_llm_backend

MAC_TEXBIN = "/Library/TeX/texbin"


@dataclass
class PreflightCheck:
    name: str
    status: str
    detail: str


def _load_requirement_names(path: str) -> List[str]:
    reqs = []
    candidate = Path(path)
    if not candidate.exists():
        return reqs
    for raw in candidate.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        # Remove environment markers and inline comments.
        line = line.split(";", 1)[0].split("#", 1)[0].strip()
        for token in ("==", ">=", "<=", "~=", "!=", ">", "<"):
            if token in line:
                line = line.split(token, 1)[0].strip()
                break
        if line:
            reqs.append(line)
    return reqs


def _check_python(min_version: Tuple[int, int] = (3, 10)) -> PreflightCheck:
    version = platform.python_version()
    major_minor = tuple(int(item) for item in version.split(".")[:2])
    if major_minor >= min_version:
        return PreflightCheck(
            name="Python version",
            status="PASS",
            detail=f"Python {version} (minimum required: {min_version[0]}.{min_version[1]}).",
        )
    return PreflightCheck(
        name="Python version",
        status="FAIL",
        detail=f"Python {version} is below required {min_version[0]}.{min_version[1]}.",
    )


def _required_packages_for_backend(resolved_backend: str) -> List[str]:
    required = list(_load_requirement_names("requirements.txt"))
    if resolved_backend == "openai":
        required.extend(_load_requirement_names("requirements-openai.txt"))
    deduped = []
    for item in required:
        if item not in deduped:
            deduped.append(item)
    return deduped


def _optional_packages() -> List[str]:
    optional = list(_load_requirement_names("requirements-optional.txt"))
    if not optional:
        optional = ["torch"]
    return optional


def _check_packages(resolution) -> PreflightCheck:
    required = _required_packages_for_backend(resolution.resolved_backend)
    missing_required = [pkg for pkg in required if importlib.util.find_spec(pkg) is None]

    optional_present = [pkg for pkg in _optional_packages() if importlib.util.find_spec(pkg) is not None]
    optional_missing = [pkg for pkg in _optional_packages() if importlib.util.find_spec(pkg) is None]

    required_text = ", ".join(required) if required else "none"
    optional_text = (
        f"optional present: {', '.join(optional_present) if optional_present else 'none'}; "
        f"optional missing: {', '.join(optional_missing) if optional_missing else 'none'}"
    )

    if missing_required:
        return PreflightCheck(
            name="Required packages",
            status="FAIL",
            detail=(
                f"Missing required package(s): {', '.join(missing_required)} "
                f"for backend '{resolution.resolved_backend}'. "
                f"Required set: {required_text}; {optional_text}."
            ),
        )

    return PreflightCheck(
        name="Required packages",
        status="PASS",
        detail=f"Required package set for backend '{resolution.resolved_backend}': {required_text}; {optional_text}.",
    )


def _check_ngspice() -> PreflightCheck:
    candidates = [
        os.getenv("NGSPICE_PATH", "").strip(),
        shutil.which("ngspice"),
        "/opt/homebrew/bin/ngspice",
        "/usr/local/bin/ngspice",
    ]
    candidate = next((item for item in candidates if item and os.path.exists(item)), None)
    if candidate:
        return PreflightCheck(
            name="ngspice availability",
            status="PASS",
            detail=f"Found ngspice at {candidate}.",
        )
    return PreflightCheck(
        name="ngspice availability",
        status="WARN",
        detail=(
            "ngspice not found. Flow will degrade to topology/sizing/netlist generation "
            "without simulation."
        ),
    )


def _check_artifacts_dir(path: str = "artifacts") -> PreflightCheck:
    try:
        os.makedirs(path, exist_ok=True)
        with tempfile.NamedTemporaryFile(mode="w", dir=path, delete=False, prefix="preflight_", suffix=".tmp") as handle:
            handle.write("ok")
            temp_path = handle.name
        os.unlink(temp_path)
        return PreflightCheck(
            name="Writable artifacts directory",
            status="PASS",
            detail=f"Artifacts directory '{path}' is writable.",
        )
    except Exception as exc:
        return PreflightCheck(
            name="Writable artifacts directory",
            status="FAIL",
            detail=f"Could not write to '{path}': {exc}",
        )


def _scan_model_libraries() -> List[Path]:
    from_env = os.getenv("DEVICE_LIBRARY_DIRS", "").strip()
    if from_env:
        roots = [Path(item) for item in from_env.split(os.pathsep) if item.strip()]
    else:
        roots = [Path("spicefiles"), Path("models"), Path("libraries"), Path("lib")]

    suffixes = {".lib", ".mod", ".mdl", ".model", ".sp", ".cir", ".scs"}
    found = []
    for root in roots:
        if not root.exists() or not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file() and path.suffix.lower() in suffixes:
                found.append(path)
    return found


def _embedded_model_cards_available() -> bool:
    candidate = Path("agents") / "netlist_agent.py"
    if not candidate.exists():
        return False
    text = candidate.read_text()
    return (".model NMOS" in text) or (".model PMOS" in text)


def _check_device_model_libraries() -> PreflightCheck:
    files = _scan_model_libraries()
    embedded_cards = _embedded_model_cards_available()

    if files:
        preview = ", ".join(str(path) for path in files[:6])
        suffix = "" if len(files) <= 6 else f" (+{len(files) - 6} more)"
        return PreflightCheck(
            name="Device/model libraries",
            status="PASS",
            detail=f"Detected {len(files)} library/source files: {preview}{suffix}",
        )

    if embedded_cards:
        return PreflightCheck(
            name="Device/model libraries",
            status="PASS",
            detail=(
                "No external library files found, but embedded transistor model cards are "
                "available in netlist templates."
            ),
        )

    return PreflightCheck(
        name="Device/model libraries",
        status="WARN",
        detail=(
            "No external model/library files detected and no embedded model cards found. "
            "Netlist generation may be possible, but simulation fidelity may be limited."
        ),
    )


def _check_llm_backend(resolution) -> PreflightCheck:
    status = "PASS"
    if resolution.fallback_used:
        status = "WARN"
    return PreflightCheck(
        name="Configured LLM backend",
        status=status,
        detail=(
            f"configured={resolution.configured_backend}; resolved={resolution.resolved_backend}; "
            f"{resolution.message}"
        ),
    )


def _check_hf_netlist_backend() -> PreflightCheck:
    has_client = importlib.util.find_spec("gradio_client") is not None
    enabled = os.getenv("USE_HF_NETLIST", "0").strip() == "1"
    space_id = os.getenv("HF_SPACE_ID", "potatoman869/spice_netlist-generator").strip()
    details = [
        f"gradio_client={'installed' if has_client else 'missing'}",
        f"USE_HF_NETLIST={'1' if enabled else '0'}",
        f"HF_SPACE_ID={space_id or 'not set'}",
    ]

    if os.getenv("RUN_HF_PREFLIGHT", "0").strip() == "1" and enabled and has_client and space_id:
        try:
            from gradio_client import Client

            Client(space_id)
            details.append("lightweight connection object created")
        except Exception as exc:
            return PreflightCheck(
                name="Hugging Face netlist backend",
                status="WARN",
                detail="; ".join(details + [f"connection test failed: {exc}"]),
            )

    if enabled and has_client and space_id:
        return PreflightCheck(
            name="Hugging Face netlist backend",
            status="PASS",
            detail="; ".join(details),
        )
    return PreflightCheck(
        name="Hugging Face netlist backend",
        status="WARN",
        detail="; ".join(details + ["deterministic fallback remains available"]),
    )


def _which_with_tex_path(tool: str) -> str | None:
    found = shutil.which(tool)
    if found:
        return found
    candidate = Path(MAC_TEXBIN) / tool
    if candidate.exists():
        return str(candidate)
    return None


def _check_lcapy_schematic_backend() -> PreflightCheck:
    has_lcapy = importlib.util.find_spec("lcapy") is not None
    latex_tools = {
        "pdflatex": _which_with_tex_path("pdflatex"),
        "latex": _which_with_tex_path("latex"),
        "kpsewhich": _which_with_tex_path("kpsewhich"),
    }
    circuitikz_detail = "not checked"
    if latex_tools["kpsewhich"]:
        try:
            import subprocess

            env = os.environ.copy()
            if Path(MAC_TEXBIN).exists():
                env["PATH"] = os.pathsep.join([MAC_TEXBIN, env.get("PATH", "")])
            probe = subprocess.run(
                [latex_tools["kpsewhich"], "circuitikz.sty"],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
                env=env,
            )
            circuitikz_detail = "found" if probe.returncode == 0 and probe.stdout.strip() else "not found"
        except Exception as exc:
            circuitikz_detail = f"check failed: {exc}"

    detail = (
        f"lcapy={'installed' if has_lcapy else 'missing'}; "
        f"pdflatex={'found' if latex_tools['pdflatex'] else 'missing'}; "
        f"latex={'found' if latex_tools['latex'] else 'missing'}; "
        f"circuitikz={circuitikz_detail}"
    )
    if has_lcapy:
        return PreflightCheck(
            name="Lcapy schematic backend",
            status="PASS",
            detail=detail,
        )
    return PreflightCheck(
        name="Lcapy schematic backend",
        status="WARN",
        detail=detail + "; fallback schematic renderer remains available.",
    )


def run_preflight_checks() -> dict:
    llm_resolution = resolve_llm_backend(instantiate=False)
    checks = [
        _check_python(),
        _check_packages(llm_resolution),
        _check_ngspice(),
        _check_artifacts_dir(),
        _check_llm_backend(llm_resolution),
        _check_device_model_libraries(),
        _check_hf_netlist_backend(),
        _check_lcapy_schematic_backend(),
    ]

    counts = {
        "PASS": sum(1 for item in checks if item.status == "PASS"),
        "WARN": sum(1 for item in checks if item.status == "WARN"),
        "FAIL": sum(1 for item in checks if item.status == "FAIL"),
    }

    return {
        "checks": checks,
        "counts": counts,
        "ok": counts["FAIL"] == 0,
        "llm_resolution": llm_resolution,
    }


def format_preflight_report(report: dict) -> str:
    lines = [
        "",
        "=== I13 Preflight ===",
    ]

    for check in report.get("checks", []):
        lines.append(f"[{check.status}] {check.name}: {check.detail}")

    counts = report.get("counts", {})
    lines.append(
        "Summary: "
        f"{counts.get('PASS', 0)} pass, "
        f"{counts.get('WARN', 0)} warn, "
        f"{counts.get('FAIL', 0)} fail"
    )
    sanity = report.get("profile_sanity") or {}
    if sanity.get("cases"):
        lines.append(
            "Profile sanity checks: "
            f"{len(sanity.get('cases', [])) - len(sanity.get('failures', []))}/"
            f"{len(sanity.get('cases', []))} passed"
        )

    if report.get("ok"):
        lines.append("Preflight status: READY (with warnings if listed above).")
    else:
        lines.append("Preflight status: BLOCKED (resolve FAIL items before sponsor demo).")

    return "\n".join(lines)
