#!/usr/bin/env python3
import importlib.util
import os
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from llm.netlist_backends import cleanup_spice_netlist, stringify_backend_response


OUT_DIR = Path("artifacts/showcase_runs/latest/hf_backend_test")
SPACE_ID = os.getenv("HF_SPACE_ID", "potatoman869/spice_netlist-generator")


def _looks_like_spice(text: str) -> bool:
    has_end = bool(re.search(r"^\s*\.end\b", text or "", flags=re.IGNORECASE | re.MULTILINE))
    has_element = bool(re.search(r"^\s*[RCLVIMQXI]\w*\s+\S+\s+\S+", text or "", flags=re.IGNORECASE | re.MULTILINE))
    return has_end and has_element


def _write_report(status: str, detail: str, raw: str = "", cleaned: str = "") -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "raw_response.txt").write_text(raw or detail or "", encoding="utf-8")
    (OUT_DIR / "cleaned_generated.sp").write_text(cleaned or "", encoding="utf-8")
    lines = [
        "# Hugging Face Netlist Backend Test",
        "",
        f"- Status: {status}",
        f"- Space: `{SPACE_ID}`",
        f"- gradio_client installed: {importlib.util.find_spec('gradio_client') is not None}",
        f"- USE_HF_NETLIST: `{os.getenv('USE_HF_NETLIST', '0')}`",
        "",
        "## Detail",
        "",
        detail,
        "",
        "## Fallback Instructions",
        "",
        "The main showcase remains safe: run `bash run_final_showcase.sh safe` for the offline deterministic path. "
        "For HF mode, install `gradio_client`, set `USE_HF_NETLIST=1`, set `HF_SPACE_ID=potatoman869/spice_netlist-generator`, "
        "and rerun `venv/bin/python3 tools/test_hf_netlist_backend.py`.",
    ]
    (OUT_DIR / "backend_test_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    prompt = (
        "Return only a valid ngspice netlist for a first-order RC low-pass filter. "
        "Use Vin in 0 AC 1, R1 in out 15915, C1 out 0 10n, include .control with op and ac, and include .end."
    )

    if importlib.util.find_spec("gradio_client") is None:
        detail = "FAIL: python package `gradio_client` is not installed."
        _write_report("FAIL", detail)
        print(detail)
        print("Fallback: run `bash run_final_showcase.sh safe` or install optional dependencies.")
        return 0

    try:
        from gradio_client import Client

        kwargs = {}
        token = os.getenv("HF_TOKEN", "").strip()
        if token:
            kwargs["hf_token"] = token
        client = Client(SPACE_ID, **kwargs)
        errors = []
        response = None
        for call in (
            lambda: client.predict(prompt, api_name="/predict"),
            lambda: client.predict(prompt),
        ):
            try:
                response = call()
                break
            except Exception as exc:
                errors.append(str(exc))
        if response is None:
            raise RuntimeError("; ".join(errors) or "HF Space prediction failed")

        raw = stringify_backend_response(response)
        cleaned = cleanup_spice_netlist(raw, required_analyses=["op", "ac"])
        if _looks_like_spice(cleaned):
            detail = "PASS: returned text contains recognizable SPICE elements and `.end`."
            _write_report("PASS", detail, raw=raw, cleaned=cleaned)
            print(detail)
            print(f"Report: {OUT_DIR / 'backend_test_report.md'}")
            return 0

        detail = "FAIL: response did not contain both recognizable SPICE elements and `.end`."
        _write_report("FAIL", detail, raw=raw, cleaned=cleaned)
        print(detail)
        print(f"Report: {OUT_DIR / 'backend_test_report.md'}")
        return 0
    except Exception as exc:
        detail = f"FAIL: Hugging Face backend test failed: {exc}"
        _write_report("FAIL", detail)
        print(detail)
        print("Fallback: run `bash run_final_showcase.sh safe`; HF failure will not crash the main demo.")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
