#!/usr/bin/env python3
"""Generate a presentation-quality schematic image for a SPICE netlist.

Three rendering paths are tried in order:

1. ``_render_topology_specific`` — for the curated demo topologies, draw a
   clean topology-specific schematic using matplotlib. This is what the live
   showcase relies on. Status is ``topology_schematic`` when this path runs.
2. ``_try_lcapy`` — passive networks pass through Lcapy when LaTeX/dvipng are
   available. Status is ``exact_lcapy``.
3. ``_draw_fallback_graph`` — generic left-to-right fallback used for
   unfamiliar topologies. Status is ``fallback_graph``.
"""
import argparse
import json
import math
import os
import re
import signal
import tempfile
from pathlib import Path

os.environ.setdefault("MPLCONFIGDIR", os.path.join(tempfile.gettempdir(), "i13-mplconfig"))
MAC_TEXBIN = "/Library/TeX/texbin"


def _ensure_tex_path() -> None:
    path_parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    if Path(MAC_TEXBIN).exists() and MAC_TEXBIN not in path_parts:
        os.environ["PATH"] = os.pathsep.join([MAC_TEXBIN] + path_parts)


_TOPOLOGY_ALIASES = {
    "rc": "rc_lowpass",
    "rc_lowpass": "rc_lowpass",
    "adc_anti_alias_rc": "rc_lowpass",
    "dac_reference_conditioning": "rc_lowpass",
    "compensation_network_helper": "rc_lowpass",
    "rlc_bandpass_2nd_order": "rlc_bandpass",
    "rlc_bandpass": "rlc_bandpass",
    "rlc_lowpass_2nd_order": "rlc_lowpass",
    "rlc_highpass_2nd_order": "rlc_highpass",
    "common_source_res_load": "common_source",
    "common_source_active_load": "common_source",
    "source_degenerated_cs": "common_source",
    "common_drain": "common_drain",
    "common_gate": "common_gate",
    "diff_pair": "diff_pair",
    "diff_pair_resistor_load": "diff_pair",
    "diff_pair_current_mirror_load": "diff_pair",
    "diff_pair_active_load": "diff_pair",
    "current_mirror": "current_mirror",
    "wilson_current_mirror": "current_mirror",
    "cascode_current_mirror": "current_mirror",
    "wide_swing_current_mirror": "current_mirror",
    "widlar_current_mirror": "current_mirror",
    "folded_cascode_opamp": "folded_cascode_opamp",
    "folded_cascode_opamp_core": "folded_cascode_opamp",
    "telescopic_cascode_opamp": "folded_cascode_opamp",
    "telescopic_cascode_opamp_core": "folded_cascode_opamp",
    "two_stage_miller": "folded_cascode_opamp",
    "ldo_error_amp_core": "folded_cascode_opamp",
}


def generate_schematic(netlist_path: str, out: str, topology: str = None, sizing: dict = None, constraints: dict = None) -> dict:
    netlist_path = str(netlist_path)
    out = str(out)
    svg_path = str(Path(out).with_suffix(".svg"))
    text = Path(netlist_path).read_text()
    sizing = sizing or {}
    constraints = constraints or {}

    topology_kind = _TOPOLOGY_ALIASES.get((topology or "").strip().lower())
    if topology_kind is not None:
        topo_result = _render_topology_specific(topology_kind, text, out, svg_path, sizing, constraints)
        if topo_result.get("schematic_status") == "topology_schematic":
            return topo_result

    devices = parse_devices(text)
    lcapy_result = _try_lcapy(text, out, svg_path) if devices else _failed("no drawable devices found")
    if lcapy_result.get("schematic_status") == "exact_lcapy":
        return lcapy_result

    fallback_result = _draw_fallback_graph(text, out, svg_path)
    if fallback_result.get("schematic_status") != "failed":
        if lcapy_result.get("schematic_failure_reason"):
            fallback_result["schematic_failure_reason"] = (
                "lcapy unavailable/failed; used fallback graph. "
                + lcapy_result["schematic_failure_reason"]
            )
        return fallback_result

    return {
        "schematic_png_path": None,
        "schematic_svg_path": None,
        "schematic_status": "failed",
        "schematic_failure_reason": (
            lcapy_result.get("schematic_failure_reason")
            or fallback_result.get("schematic_failure_reason")
            or "no schematic backend succeeded"
        ),
    }


# ---------------------------------------------------------------------------
# Netlist parsing helpers
# ---------------------------------------------------------------------------


def parse_devices(text: str) -> list[dict]:
    devices = []
    in_control = False
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        lower = line.lower()
        if lower.startswith(".control"):
            in_control = True
            continue
        if lower.startswith(".endc"):
            in_control = False
            continue
        if in_control or line.startswith("."):
            continue
        tokens = line.split()
        if not tokens:
            continue
        name = tokens[0]
        prefix = name[0].upper()
        if prefix in {"R", "C", "L", "V", "I"} and len(tokens) >= 4:
            devices.append(
                {
                    "name": name,
                    "kind": prefix,
                    "nodes": tokens[1:3],
                    "value": tokens[3],
                    "terminal_labels": ["+", "-"] if prefix in {"V", "I"} else ["1", "2"],
                }
            )
        elif prefix == "M" and len(tokens) >= 6:
            devices.append(
                {
                    "name": name,
                    "kind": "M",
                    "nodes": tokens[1:5],
                    "value": tokens[5],
                    "params": tokens[6:],
                    "terminal_labels": ["D", "G", "S", "B"],
                }
            )
        elif prefix == "Q" and len(tokens) >= 5:
            devices.append(
                {
                    "name": name,
                    "kind": "Q",
                    "nodes": tokens[1:4],
                    "value": tokens[4],
                    "terminal_labels": ["C", "B", "E"],
                }
            )
    return devices


def _format_value(value: str, kind: str) -> str:
    if value is None or value == "":
        return ""
    text = str(value).strip()
    try:
        number = float(text)
    except ValueError:
        return text
    units = {"R": "Ω", "C": "F", "L": "H", "V": "V", "I": "A"}.get(kind, "")
    return _humanize(number, units)


def _humanize(number: float, units: str) -> str:
    if number == 0:
        return f"0 {units}".strip()
    abs_v = abs(number)
    prefixes = [
        (1e12, "T"),
        (1e9, "G"),
        (1e6, "M"),
        (1e3, "k"),
        (1.0, ""),
        (1e-3, "m"),
        (1e-6, "µ"),
        (1e-9, "n"),
        (1e-12, "p"),
        (1e-15, "f"),
    ]
    for scale, prefix in prefixes:
        if abs_v >= scale or scale == 1e-15:
            value = number / scale
            text = f"{value:.3g}"
            return f"{text} {prefix}{units}".strip()
    return f"{number:g} {units}".strip()


def _device_value(devices, prefix, fallback=""):
    for device in devices:
        if device.get("name", "").upper().startswith(prefix.upper()):
            return _format_value(device.get("value"), device.get("kind", ""))
    return fallback


# ---------------------------------------------------------------------------
# Common matplotlib helpers
# ---------------------------------------------------------------------------


def _make_axes(width=11.0, height=6.0):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(width, height))
    ax.set_aspect("equal")
    ax.axis("off")
    return plt, fig, ax


def _save(plt, fig, png_path: str, svg_path: str) -> tuple[str, str]:
    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=180, bbox_inches="tight", facecolor="white")
    fig.savefig(svg_path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    return (
        png_path if os.path.exists(png_path) else None,
        svg_path if os.path.exists(svg_path) else None,
    )


def _wire(ax, x1, y1, x2, y2, color="#1f2937", linewidth=1.6, zorder=1):
    ax.plot([x1, x2], [y1, y2], color=color, linewidth=linewidth, zorder=zorder)


def _node_dot(ax, x, y, color="#1f2937"):
    ax.scatter([x], [y], s=22, color=color, zorder=5)


def _label(ax, x, y, text, fontsize=10, color="#0f172a", weight="normal", ha="center", va="center", boxed=False):
    bbox = None
    if boxed:
        bbox = dict(boxstyle="round,pad=0.18", fc="white", ec="#cbd5e1", lw=0.8)
    ax.text(x, y, text, fontsize=fontsize, color=color, weight=weight, ha=ha, va=va, zorder=6, bbox=bbox)


def _draw_resistor(ax, x1, y1, x2, y2, label_text="", label_offset=(0.0, 0.32)):
    """Draw a resistor between (x1,y1) and (x2,y2) as a zig-zag rectangle."""
    import numpy as np

    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    body_len = max(length * 0.55, 0.55)
    body_start = ((x1 + x2) / 2 - ux * body_len / 2, (y1 + y2) / 2 - uy * body_len / 2)
    body_end = ((x1 + x2) / 2 + ux * body_len / 2, (y1 + y2) / 2 + uy * body_len / 2)
    half_w = 0.16
    rect_corners = [
        (body_start[0] + nx * half_w, body_start[1] + ny * half_w),
        (body_end[0] + nx * half_w, body_end[1] + ny * half_w),
        (body_end[0] - nx * half_w, body_end[1] - ny * half_w),
        (body_start[0] - nx * half_w, body_start[1] - ny * half_w),
    ]
    from matplotlib.patches import Polygon

    ax.add_patch(Polygon(rect_corners, closed=True, facecolor="#fff7ed", edgecolor="#b45309", linewidth=1.6, zorder=3))
    _wire(ax, x1, y1, body_start[0], body_start[1])
    _wire(ax, body_end[0], body_end[1], x2, y2)
    if label_text:
        cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
        _label(ax, cx + label_offset[0], cy + label_offset[1], label_text, fontsize=9, color="#7c2d12", weight="bold")


def _draw_capacitor(ax, x1, y1, x2, y2, label_text=""):
    cx, cy = (x1 + x2) / 2, (y1 + y2) / 2
    if abs(x2 - x1) > abs(y2 - y1):
        # horizontal capacitor
        plate_x = cx
        plate_h = 0.32
        ax.plot([plate_x - 0.05, plate_x - 0.05], [cy - plate_h, cy + plate_h], color="#155e75", linewidth=2.2, zorder=3)
        ax.plot([plate_x + 0.05, plate_x + 0.05], [cy - plate_h, cy + plate_h], color="#155e75", linewidth=2.2, zorder=3)
        _wire(ax, x1, y1, plate_x - 0.05, cy)
        _wire(ax, plate_x + 0.05, cy, x2, y2)
        if label_text:
            _label(ax, cx, cy + 0.55, label_text, fontsize=9, color="#155e75", weight="bold")
    else:
        plate_y = cy
        plate_w = 0.32
        ax.plot([cx - plate_w, cx + plate_w], [plate_y - 0.05, plate_y - 0.05], color="#155e75", linewidth=2.2, zorder=3)
        ax.plot([cx - plate_w, cx + plate_w], [plate_y + 0.05, plate_y + 0.05], color="#155e75", linewidth=2.2, zorder=3)
        _wire(ax, x1, y1, cx, plate_y - 0.05)
        _wire(ax, cx, plate_y + 0.05, x2, y2)
        if label_text:
            _label(ax, cx + 0.55, plate_y, label_text, fontsize=9, color="#155e75", weight="bold", ha="left")


def _draw_inductor(ax, x1, y1, x2, y2, label_text=""):
    import numpy as np

    dx = x2 - x1
    dy = y2 - y1
    length = math.hypot(dx, dy)
    if length == 0:
        return
    ux, uy = dx / length, dy / length
    nx, ny = -uy, ux
    body_len = max(length * 0.6, 0.6)
    cx = (x1 + x2) / 2
    cy = (y1 + y2) / 2
    start = (cx - ux * body_len / 2, cy - uy * body_len / 2)
    end = (cx + ux * body_len / 2, cy + uy * body_len / 2)
    _wire(ax, x1, y1, start[0], start[1])
    _wire(ax, end[0], end[1], x2, y2)
    coils = 4
    radius = 0.12
    from matplotlib.patches import Arc

    for idx in range(coils):
        t = (idx + 0.5) / coils
        bx = start[0] + (end[0] - start[0]) * t
        by = start[1] + (end[1] - start[1]) * t
        if abs(ux) > abs(uy):
            ax.add_patch(Arc((bx, by), radius * 2, radius * 2, theta1=0, theta2=180, color="#6d28d9", linewidth=1.8, zorder=3))
        else:
            ax.add_patch(Arc((bx, by), radius * 2, radius * 2, theta1=270, theta2=90, color="#6d28d9", linewidth=1.8, zorder=3))
    if label_text:
        offset = (nx * 0.4, ny * 0.4) if abs(ux) > abs(uy) else (nx * 0.55, ny * 0.55)
        _label(ax, cx + offset[0], cy + offset[1], label_text, fontsize=9, color="#6d28d9", weight="bold")


def _draw_ground(ax, x, y, label="GND"):
    _wire(ax, x, y, x, y - 0.18)
    ax.plot([x - 0.32, x + 0.32], [y - 0.18, y - 0.18], color="#1f2937", linewidth=2.2, zorder=3)
    ax.plot([x - 0.22, x + 0.22], [y - 0.30, y - 0.30], color="#1f2937", linewidth=1.8, zorder=3)
    ax.plot([x - 0.12, x + 0.12], [y - 0.42, y - 0.42], color="#1f2937", linewidth=1.4, zorder=3)
    if label:
        _label(ax, x, y - 0.62, label, fontsize=8.5, color="#475569")


def _draw_vdd(ax, x, y, label="VDD"):
    _wire(ax, x, y, x, y + 0.22)
    ax.plot([x - 0.36, x + 0.36], [y + 0.22, y + 0.22], color="#b45309", linewidth=2.6, zorder=3)
    if label:
        _label(ax, x, y + 0.45, label, fontsize=9, color="#92400e", weight="bold")


def _draw_io_terminal(ax, x, y, label, side="left"):
    color = "#1d4ed8" if side == "left" else "#15803d"
    bg = "#dbeafe" if side == "left" else "#dcfce7"
    ax.scatter([x], [y], s=120, color=bg, edgecolors=color, linewidths=1.6, zorder=4)
    if side == "left":
        _label(ax, x - 0.18, y, label, fontsize=10, color=color, weight="bold", ha="right")
    else:
        _label(ax, x + 0.18, y, label, fontsize=10, color=color, weight="bold", ha="left")


def _draw_nmos(ax, x, y, label_above="", label_below="", drain_label="", source_label="", gate_label="G", w_h=(0.45, 0.55), arrow=True, body_label=None):
    """Draw an NMOS transistor centred at (x,y) with vertical channel.

    The drain pin is at (x, y + h), source at (x, y - h), gate at (x - w - 0.4, y).
    """
    w, h = w_h
    from matplotlib.patches import Rectangle

    # channel
    ax.add_patch(Rectangle((x - w, y - h), 2 * w, 2 * h, fill=False, edgecolor="#0f172a", linewidth=0))
    # drain wire
    ax.plot([x, x], [y - h, y + h], color="#1f2937", linewidth=1.4, zorder=2)
    # gate
    ax.plot([x - w - 0.55, x - w - 0.05], [y, y], color="#1f2937", linewidth=1.6)
    ax.plot([x - w - 0.05, x - w - 0.05], [y - h * 0.65, y + h * 0.65], color="#0f172a", linewidth=2.4)
    if arrow:
        # NMOS arrow points into channel (towards source)
        ax.annotate(
            "",
            xy=(x, y - h * 0.45),
            xytext=(x - w * 0.55, y - h * 0.65),
            arrowprops=dict(arrowstyle="->", color="#0f172a", lw=1.4),
        )
    if label_above:
        _label(ax, x + w + 0.6, y + h * 0.7, label_above, fontsize=9, color="#0f172a", ha="left", weight="bold")
    if label_below:
        _label(ax, x + w + 0.6, y - h * 0.7, label_below, fontsize=9, color="#475569", ha="left")
    if gate_label:
        _label(ax, x - w - 0.7, y, gate_label, fontsize=8.5, color="#1d4ed8", ha="right")


def _draw_pmos(ax, x, y, label_above="", label_below="", w_h=(0.45, 0.55)):
    w, h = w_h
    ax.plot([x, x], [y - h, y + h], color="#1f2937", linewidth=1.4, zorder=2)
    ax.plot([x - w - 0.55, x - w - 0.05], [y, y], color="#1f2937", linewidth=1.6)
    ax.plot([x - w - 0.05, x - w - 0.05], [y - h * 0.65, y + h * 0.65], color="#0f172a", linewidth=2.4)
    # PMOS bubble at gate side
    from matplotlib.patches import Circle

    ax.add_patch(Circle((x - w - 0.18, y), 0.08, fill=False, edgecolor="#0f172a", linewidth=1.4, zorder=4))
    ax.annotate(
        "",
        xy=(x - w * 0.55, y + h * 0.65),
        xytext=(x, y + h * 0.45),
        arrowprops=dict(arrowstyle="->", color="#0f172a", lw=1.4),
    )
    if label_above:
        _label(ax, x + w + 0.6, y + h * 0.7, label_above, fontsize=9, color="#0f172a", ha="left", weight="bold")
    if label_below:
        _label(ax, x + w + 0.6, y - h * 0.7, label_below, fontsize=9, color="#475569", ha="left")


def _diode_connect(ax, x_drain, y_drain, x_gate, y_gate):
    """Draw a small wire showing diode connection between drain and gate nodes."""
    _wire(ax, x_drain, y_drain, x_drain + 0.22, y_drain, color="#0f172a", linewidth=1.4)
    _wire(ax, x_drain + 0.22, y_drain, x_drain + 0.22, y_gate, color="#0f172a", linewidth=1.4)
    _wire(ax, x_drain + 0.22, y_gate, x_gate, y_gate, color="#0f172a", linewidth=1.4)
    _node_dot(ax, x_drain, y_drain)


# ---------------------------------------------------------------------------
# Topology-specific renderers
# ---------------------------------------------------------------------------


def _render_topology_specific(kind: str, text: str, png_path: str, svg_path: str, sizing: dict, constraints: dict) -> dict:
    try:
        devices = parse_devices(text)
        if kind == "rc_lowpass":
            return _render_rc_lowpass(devices, png_path, svg_path, sizing, constraints)
        if kind == "rlc_bandpass":
            return _render_rlc_bandpass(devices, png_path, svg_path, sizing, constraints)
        if kind == "rlc_lowpass":
            return _render_rlc_lowpass(devices, png_path, svg_path, sizing, constraints)
        if kind == "rlc_highpass":
            return _render_rlc_highpass(devices, png_path, svg_path, sizing, constraints)
        if kind == "common_source":
            return _render_common_source(devices, png_path, svg_path, sizing, constraints)
        if kind == "common_drain":
            return _render_common_drain(devices, png_path, svg_path, sizing, constraints)
        if kind == "current_mirror":
            return _render_current_mirror(devices, png_path, svg_path, sizing, constraints)
        if kind == "diff_pair":
            return _render_diff_pair(devices, png_path, svg_path, sizing, constraints)
        if kind == "folded_cascode_opamp":
            return _render_opamp_block(devices, png_path, svg_path, sizing, constraints)
    except Exception as exc:
        return _failed(f"topology renderer crashed: {exc}")
    return _failed(f"no topology renderer for '{kind}'")


def _render_rc_lowpass(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=8.5, height=4.5)
    ax.set_xlim(-0.4, 8.5)
    ax.set_ylim(-1.5, 2.5)

    in_x, in_y = 0.4, 1.4
    r_left = (1.4, 1.4)
    r_right = (4.6, 1.4)
    out_x, out_y = 6.4, 1.4
    cap_top = (out_x - 0.6, 1.4)
    cap_bot = (out_x - 0.6, 0.0)

    _draw_io_terminal(ax, in_x, in_y, "VIN", side="left")
    _wire(ax, in_x, in_y, r_left[0], r_left[1])
    r_label = _device_value(devices, "R", _humanize(_safe_float(sizing.get("R_ohm")) or 0.0, "Ω"))
    _draw_resistor(ax, r_left[0], r_left[1], r_right[0], r_right[1], label_text=f"R1 = {r_label}")
    _wire(ax, r_right[0], r_right[1], cap_top[0], cap_top[1])
    _node_dot(ax, cap_top[0], cap_top[1])
    _wire(ax, cap_top[0], cap_top[1], out_x, out_y)
    _draw_io_terminal(ax, out_x, out_y, "VOUT", side="right")
    c_label = _device_value(devices, "C", _humanize(_safe_float(sizing.get("C_f")) or 0.0, "F"))
    _draw_capacitor(ax, cap_top[0], cap_top[1], cap_bot[0], cap_bot[1], label_text=f"C1 = {c_label}")
    _draw_ground(ax, cap_bot[0], cap_bot[1] - 0.05)

    fc_target = _safe_float(constraints.get("target_fc_hz"))
    title_extra = f"  •  target fc = {_humanize(fc_target, 'Hz')}" if fc_target else ""
    _label(ax, 4.0, 2.25, f"First-Order RC Low-Pass{title_extra}", fontsize=13, weight="bold", color="#0f172a")

    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_rlc_bandpass(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=10.0, height=5.0)
    ax.set_xlim(-0.4, 10.0)
    ax.set_ylim(-1.6, 2.6)

    _draw_io_terminal(ax, 0.4, 1.4, "VIN", side="left")
    _wire(ax, 0.4, 1.4, 1.4, 1.4)

    r_label = _device_value(devices, "R", "")
    _draw_resistor(ax, 1.4, 1.4, 3.4, 1.4, label_text=f"Rs = {r_label}" if r_label else "Rs")

    _wire(ax, 3.4, 1.4, 4.6, 1.4)
    l_label = _device_value(devices, "L", _humanize(_safe_float(sizing.get("L_h")) or 0.0, "H"))
    _draw_inductor(ax, 4.6, 1.4, 6.6, 1.4, label_text=f"L = {l_label}")

    _wire(ax, 6.6, 1.4, 7.4, 1.4)
    c_label = _device_value(devices, "C", _humanize(_safe_float(sizing.get("C_f")) or 0.0, "F"))
    _draw_capacitor(ax, 7.4, 1.4, 8.4, 1.4, label_text=f"C = {c_label}")

    _wire(ax, 8.4, 1.4, 9.0, 1.4)
    _node_dot(ax, 9.0, 1.4)
    _draw_io_terminal(ax, 9.4, 1.4, "VOUT", side="right")
    _wire(ax, 9.0, 1.4, 9.4, 1.4)

    # ground reference rail
    _wire(ax, 0.4, -0.6, 9.4, -0.6, color="#475569", linewidth=1.4)
    _wire(ax, 0.4, 1.4, 0.4, -0.6, color="#94a3b8", linewidth=1.0)
    _wire(ax, 9.4, 1.4, 9.4, -0.6, color="#94a3b8", linewidth=1.0)
    _draw_ground(ax, 4.7, -0.6)

    center = _safe_float(constraints.get("target_center_hz"))
    bw = _safe_float(constraints.get("target_bw_hz"))
    title_extra = ""
    if center:
        title_extra = f"  •  centre = {_humanize(center, 'Hz')}"
    if bw:
        title_extra += f"  •  BW = {_humanize(bw, 'Hz')}"
    _label(ax, 4.8, 2.35, f"Second-Order RLC Band-Pass{title_extra}", fontsize=12.5, weight="bold", color="#0f172a")
    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_rlc_lowpass(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=10.0, height=5.0)
    ax.set_xlim(-0.4, 10.0)
    ax.set_ylim(-1.6, 2.6)

    _draw_io_terminal(ax, 0.4, 1.4, "VIN", side="left")
    _wire(ax, 0.4, 1.4, 1.4, 1.4)
    _draw_resistor(ax, 1.4, 1.4, 3.4, 1.4, label_text=f"R = {_device_value(devices, 'R', '')}")
    _wire(ax, 3.4, 1.4, 4.4, 1.4)
    _draw_inductor(ax, 4.4, 1.4, 6.4, 1.4, label_text=f"L = {_device_value(devices, 'L', '')}")
    _wire(ax, 6.4, 1.4, 7.4, 1.4)
    _node_dot(ax, 7.4, 1.4)
    _wire(ax, 7.4, 1.4, 9.4, 1.4)
    _draw_io_terminal(ax, 9.4, 1.4, "VOUT", side="right")
    _draw_capacitor(ax, 7.4, 1.4, 7.4, 0.0, label_text=f"C = {_device_value(devices, 'C', '')}")
    _draw_ground(ax, 7.4, 0.0)

    _label(ax, 4.8, 2.35, "Second-Order RLC Low-Pass", fontsize=12.5, weight="bold", color="#0f172a")
    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_rlc_highpass(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=10.0, height=5.0)
    ax.set_xlim(-0.4, 10.0)
    ax.set_ylim(-1.6, 2.6)
    _draw_io_terminal(ax, 0.4, 1.4, "VIN", side="left")
    _wire(ax, 0.4, 1.4, 1.4, 1.4)
    _draw_capacitor(ax, 1.4, 1.4, 2.4, 1.4, label_text=f"C = {_device_value(devices, 'C', '')}")
    _wire(ax, 2.4, 1.4, 3.4, 1.4)
    _draw_inductor(ax, 3.4, 1.4, 5.4, 1.4, label_text=f"L = {_device_value(devices, 'L', '')}")
    _wire(ax, 5.4, 1.4, 6.4, 1.4)
    _node_dot(ax, 6.4, 1.4)
    _wire(ax, 6.4, 1.4, 9.4, 1.4)
    _draw_io_terminal(ax, 9.4, 1.4, "VOUT", side="right")
    _draw_resistor(ax, 6.4, 1.4, 6.4, 0.0, label_text=f"R = {_device_value(devices, 'R', '')}")
    _draw_ground(ax, 6.4, 0.0)
    _label(ax, 4.8, 2.35, "Second-Order RLC High-Pass", fontsize=12.5, weight="bold", color="#0f172a")
    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_common_source(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=9.5, height=6.0)
    ax.set_xlim(-0.4, 9.5)
    ax.set_ylim(-2.2, 4.2)

    vdd_x, vdd_y = 5.0, 3.6
    rd_top = (5.0, 3.0)
    rd_bot = (5.0, 1.6)
    drain_node = (5.0, 1.0)
    out_x, out_y = 7.6, 1.0
    gate_x, gate_y = 1.6, 0.4
    src_node = (5.0, -0.6)

    _draw_vdd(ax, vdd_x, vdd_y)
    _wire(ax, vdd_x, vdd_y - 0.05, rd_top[0], rd_top[1])
    rd_value = _device_value(devices, "R", _humanize(_safe_float(sizing.get("R_D")) or 0.0, "Ω"))
    _draw_resistor(ax, rd_top[0], rd_top[1], rd_bot[0], rd_bot[1], label_text=f"RD = {rd_value}")
    _wire(ax, rd_bot[0], rd_bot[1], drain_node[0], drain_node[1])
    _node_dot(ax, drain_node[0], drain_node[1])
    _wire(ax, drain_node[0], drain_node[1], out_x, out_y)
    _draw_io_terminal(ax, out_x, out_y, "VOUT", side="right")

    # NMOS
    w_m = _safe_float(sizing.get("W_m"))
    l_m = _safe_float(sizing.get("L_m"))
    wl_label = ""
    if w_m and l_m:
        wl_label = f"W/L = {_humanize(w_m, 'm')} / {_humanize(l_m, 'm')}"
    _draw_nmos(ax, drain_node[0], 0.4, label_above="M1", label_below=wl_label, gate_label="")

    # gate connection
    _wire(ax, gate_x, gate_y, drain_node[0] - 1.0, gate_y)
    _draw_io_terminal(ax, gate_x, gate_y, "VIN", side="left")

    # source to ground
    _wire(ax, drain_node[0], -0.15, src_node[0], src_node[1])
    _draw_ground(ax, src_node[0], src_node[1])

    # optional load cap on output
    cl = _safe_float(constraints.get("load_cap_f"))
    if cl:
        _wire(ax, out_x, out_y, out_x, out_y - 0.6)
        _draw_capacitor(ax, out_x, out_y - 0.6, out_x, -0.6, label_text=f"CL = {_humanize(cl, 'F')}")
        _draw_ground(ax, out_x, -0.6)

    title = "Common-Source Amplifier (NMOS + Resistor Load)"
    target_gain = _safe_float(constraints.get("target_gain_db"))
    target_bw = _safe_float(constraints.get("target_bw_hz"))
    extras = []
    if target_gain is not None:
        extras.append(f"target gain ≈ {target_gain:g} dB")
    if target_bw is not None:
        extras.append(f"target BW ≈ {_humanize(target_bw, 'Hz')}")
    if extras:
        title += "  •  " + ", ".join(extras)
    _label(ax, 4.6, 4.0, title, fontsize=12, weight="bold", color="#0f172a")

    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_common_drain(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=9.5, height=6.0)
    ax.set_xlim(-0.4, 9.5)
    ax.set_ylim(-2.4, 4.2)

    vdd_x, vdd_y = 4.5, 3.6
    drain_top = (vdd_x, vdd_y - 0.05)
    src_node = (vdd_x, -0.4)
    out_x, out_y = 7.4, src_node[1]
    gate_x, gate_y = 1.6, 1.5

    _draw_vdd(ax, vdd_x, vdd_y)
    _wire(ax, drain_top[0], drain_top[1], vdd_x, 1.4)
    _draw_nmos(ax, vdd_x, 0.6, label_above="M1", label_below="W/L sized", gate_label="")
    _wire(ax, gate_x, gate_y, vdd_x - 1.0, gate_y)
    _draw_io_terminal(ax, gate_x, gate_y, "VIN", side="left")
    _wire(ax, vdd_x, 0.05, src_node[0], src_node[1])
    _node_dot(ax, src_node[0], src_node[1])
    _wire(ax, src_node[0], src_node[1], out_x, out_y)
    _draw_io_terminal(ax, out_x, out_y, "VOUT", side="right")
    rs_value = _device_value(devices, "R", "Rs")
    _draw_resistor(ax, src_node[0], src_node[1], src_node[0], -1.5, label_text=f"Rs = {rs_value}")
    _draw_ground(ax, src_node[0], -1.5)
    cl = _safe_float(constraints.get("load_cap_f"))
    if cl:
        _wire(ax, out_x, out_y, out_x, out_y - 0.4)
        _draw_capacitor(ax, out_x, out_y - 0.4, out_x, -1.5, label_text=f"CL = {_humanize(cl, 'F')}")
        _draw_ground(ax, out_x, -1.5)
    _label(ax, 4.5, 4.0, "Common-Drain Source Follower", fontsize=12, weight="bold", color="#0f172a")
    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_current_mirror(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=9.5, height=6.0)
    ax.set_xlim(-0.4, 9.5)
    ax.set_ylim(-2.6, 4.2)

    vdd_y = 3.4
    iref_x = 2.0
    iout_x = 7.0
    gate_y = 1.0
    src_y = -0.6
    drain_ref_y = 1.0
    drain_out_y = 1.0

    # IREF source from VDD
    _draw_vdd(ax, iref_x, vdd_y)
    _wire(ax, iref_x, vdd_y - 0.05, iref_x, 2.6)
    # current source
    from matplotlib.patches import Circle

    ax.add_patch(Circle((iref_x, 2.3), 0.32, fill=True, facecolor="#fef3c7", edgecolor="#b45309", linewidth=1.6, zorder=3))
    _label(ax, iref_x, 2.3, "Iref", fontsize=9, color="#92400e", weight="bold")
    _wire(ax, iref_x, 2.0, iref_x, drain_ref_y)
    _node_dot(ax, iref_x, drain_ref_y)

    # M1 (diode-connected reference)
    _draw_nmos(ax, iref_x, src_y + (drain_ref_y - src_y) / 2, label_above="M1 (diode)", label_below="reference leg", gate_label="")
    # diode connect: drain to gate
    _wire(ax, iref_x, drain_ref_y, iref_x + 0.8, drain_ref_y, color="#0f172a", linewidth=1.4)
    _wire(ax, iref_x + 0.8, drain_ref_y, iref_x + 0.8, gate_y - 0.4, color="#0f172a", linewidth=1.4)
    _wire(ax, iref_x + 0.8, gate_y - 0.4, iref_x - 0.55 - 0.45, gate_y - 0.4, color="#0f172a", linewidth=1.4)
    _wire(ax, iref_x - 0.55 - 0.45, gate_y - 0.4, iref_x - 0.55 - 0.45, gate_y - 0.4 + (gate_y - 0.4 - (gate_y - 0.4)), color="#0f172a", linewidth=0.0)

    # gate rail to M2
    gate_rail_y = 0.05
    _wire(ax, iref_x + 0.8, drain_ref_y, iref_x + 0.8, gate_rail_y, color="#0f172a", linewidth=1.4)
    _wire(ax, iref_x + 0.8, gate_rail_y, iout_x - 1.05, gate_rail_y, color="#0f172a", linewidth=1.4)
    # M1 gate dot
    _node_dot(ax, iref_x - 1.0, gate_rail_y)
    _wire(ax, iref_x + 0.8, gate_rail_y, iref_x - 1.0, gate_rail_y, color="#0f172a", linewidth=1.4)

    # M2 (output mirror)
    _draw_nmos(ax, iout_x, src_y + (drain_out_y - src_y) / 2, label_above="M2", label_below="output leg", gate_label="")

    # Sources to GND
    _wire(ax, iref_x, src_y - 0.05, iref_x, -1.4)
    _draw_ground(ax, iref_x, -1.4)
    _wire(ax, iout_x, src_y - 0.05, iout_x, -1.4)
    _draw_ground(ax, iout_x, -1.4)

    # output drain up to IOUT terminal
    _wire(ax, iout_x, drain_out_y, iout_x, 2.4)
    _node_dot(ax, iout_x, drain_out_y)
    _wire(ax, iout_x, 2.4, iout_x + 1.0, 2.4)
    _draw_io_terminal(ax, iout_x + 1.0, 2.4, "IOUT", side="right")

    # input current label
    _label(ax, iref_x - 0.6, 2.3, "Iref", fontsize=9, color="#92400e", ha="right")

    iref_value = _safe_float(constraints.get("reference_current_a"))
    if iref_value is None:
        iref_value = _safe_float(sizing.get("I_ref"))
    target_iout = _safe_float(constraints.get("target_iout_a"))
    ratio = _safe_float(constraints.get("mirror_ratio"))
    title = "Current Mirror"
    extras = []
    if iref_value is not None:
        extras.append(f"Iref ≈ {_humanize(iref_value, 'A')}")
    if target_iout is not None:
        extras.append(f"Iout target ≈ {_humanize(target_iout, 'A')}")
    if ratio is not None:
        extras.append(f"ratio = {ratio:g}×")
    if extras:
        title += "  •  " + ", ".join(extras)
    _label(ax, 4.5, 4.0, title, fontsize=12, weight="bold", color="#0f172a")

    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_diff_pair(devices, png_path, svg_path, sizing, constraints):
    plt, fig, ax = _make_axes(width=10.5, height=6.0)
    ax.set_xlim(-0.4, 10.5)
    ax.set_ylim(-2.6, 4.4)

    vdd_y = 3.6
    rl_left_x = 3.5
    rl_right_x = 7.0
    drain_y = 1.4
    nmos_y = 0.4
    src_node_y = -0.5
    tail_y = -1.6
    in_left_x, in_right_x = 1.0, 9.5
    gate_y = 0.4

    _draw_vdd(ax, rl_left_x, vdd_y)
    _draw_vdd(ax, rl_right_x, vdd_y)
    _draw_resistor(ax, rl_left_x, vdd_y - 0.1, rl_left_x, drain_y, label_text="RL")
    _draw_resistor(ax, rl_right_x, vdd_y - 0.1, rl_right_x, drain_y, label_text="RL")
    _draw_nmos(ax, rl_left_x, nmos_y, label_above="M1", label_below="", gate_label="")
    _draw_nmos(ax, rl_right_x, nmos_y, label_above="M2", label_below="", gate_label="")
    _wire(ax, rl_left_x, drain_y, rl_left_x, nmos_y + 0.55)
    _wire(ax, rl_right_x, drain_y, rl_right_x, nmos_y + 0.55)
    _node_dot(ax, rl_left_x, drain_y)
    _node_dot(ax, rl_right_x, drain_y)
    _wire(ax, rl_left_x, drain_y, rl_left_x - 1.0, drain_y)
    _wire(ax, rl_right_x, drain_y, rl_right_x + 1.0, drain_y)
    _draw_io_terminal(ax, rl_left_x - 1.0, drain_y, "VOUT-", side="left")
    _draw_io_terminal(ax, rl_right_x + 1.0, drain_y, "VOUT+", side="right")
    # gates
    _wire(ax, rl_left_x - 0.55 - 0.5, gate_y, in_left_x, gate_y)
    _wire(ax, rl_right_x - 0.55 - 0.5, gate_y, in_right_x, gate_y)
    _draw_io_terminal(ax, in_left_x, gate_y, "VIN+", side="left")
    _draw_io_terminal(ax, in_right_x, gate_y, "VIN-", side="right")
    # tail node
    _wire(ax, rl_left_x, nmos_y - 0.55, rl_left_x, src_node_y)
    _wire(ax, rl_right_x, nmos_y - 0.55, rl_right_x, src_node_y)
    _wire(ax, rl_left_x, src_node_y, rl_right_x, src_node_y)
    _node_dot(ax, (rl_left_x + rl_right_x) / 2, src_node_y)
    # tail current source
    from matplotlib.patches import Circle

    tail_x = (rl_left_x + rl_right_x) / 2
    _wire(ax, tail_x, src_node_y, tail_x, tail_y + 0.35)
    ax.add_patch(Circle((tail_x, tail_y), 0.32, fill=True, facecolor="#fef3c7", edgecolor="#b45309", linewidth=1.6, zorder=3))
    _label(ax, tail_x, tail_y, "Itail", fontsize=9, color="#92400e", weight="bold")
    _wire(ax, tail_x, tail_y - 0.32, tail_x, -2.2)
    _draw_ground(ax, tail_x, -2.2)

    _label(ax, 5.0, 4.2, "NMOS Differential Pair", fontsize=12.5, weight="bold", color="#0f172a")
    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _render_opamp_block(devices, png_path, svg_path, sizing, constraints):
    """Block-level diagram for folded-cascode / two-stage / telescopic op amps."""
    plt, fig, ax = _make_axes(width=11.0, height=6.0)
    ax.set_xlim(-0.4, 11.0)
    ax.set_ylim(-1.5, 4.4)
    from matplotlib.patches import FancyBboxPatch

    def _block(x, y, w, h, label, sub=""):
        patch = FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0.04,rounding_size=0.12",
                               facecolor="#eef2ff", edgecolor="#312e81", linewidth=1.6, zorder=3)
        ax.add_patch(patch)
        _label(ax, x + w / 2, y + h / 2 + (0.18 if sub else 0.0), label, fontsize=11, color="#1e1b4b", weight="bold")
        if sub:
            _label(ax, x + w / 2, y + h / 2 - 0.22, sub, fontsize=8.5, color="#475569")

    # rails
    _wire(ax, 0.4, 3.7, 10.6, 3.7, color="#b45309", linewidth=2.2)
    _label(ax, 0.4, 3.95, "VDD", fontsize=9, color="#92400e", weight="bold")
    _wire(ax, 0.4, -1.2, 10.6, -1.2, color="#1f2937", linewidth=2.2)
    _label(ax, 0.4, -1.42, "VSS / GND", fontsize=9, color="#1f2937", weight="bold")

    # input terminals
    _draw_io_terminal(ax, 0.6, 1.9, "VIN+", side="left")
    _draw_io_terminal(ax, 0.6, 1.0, "VIN-", side="left")

    # diff pair
    _block(1.6, 0.6, 2.2, 1.7, "Differential\nInput Pair", sub="NMOS pair, tail bias")
    _wire(ax, 0.95, 1.9, 1.6, 1.9)
    _wire(ax, 0.95, 1.0, 1.6, 1.0)

    # folded-cascode core
    _block(4.4, 0.4, 2.6, 2.1, "Folded\nCascode Core", sub="cascode + bias mirrors")
    _wire(ax, 3.8, 1.5, 4.4, 1.5)

    # output node
    out_x = 7.7
    out_y = 1.5
    _block(out_x, out_y - 0.55, 1.4, 1.1, "Output\nNode", sub="high-Z drive")
    _wire(ax, 7.0, out_y, out_x, out_y)

    # CL load
    cl = _safe_float(constraints.get("load_cap_f"))
    cl_label = f"CL = {_humanize(cl, 'F')}" if cl else "CL"
    _draw_capacitor(ax, out_x + 1.6, out_y, out_x + 1.6, -0.4, label_text=cl_label)
    _wire(ax, out_x + 1.4, out_y, out_x + 1.6, out_y)
    _draw_ground(ax, out_x + 1.6, -0.4)

    # output terminal
    _draw_io_terminal(ax, 10.4, out_y, "VOUT", side="right")
    _wire(ax, out_x + 1.4, out_y, 10.4, out_y)

    # bias network block (lower)
    _block(4.4, -0.9, 2.6, 0.9, "Bias Network", sub="Vbn / Vbp generators")
    _wire(ax, 5.7, -0.9, 5.7, -1.2)

    # title with targets
    target_gain = _safe_float(constraints.get("target_gain_db"))
    target_ugbw = _safe_float(constraints.get("target_ugbw_hz"))
    title = "Folded-Cascode Op Amp (block diagram)"
    extras = []
    if target_gain is not None:
        extras.append(f"target gain ≈ {target_gain:g} dB")
    if target_ugbw is not None:
        extras.append(f"target UGBW ≈ {_humanize(target_ugbw, 'Hz')}")
    if cl is not None:
        extras.append(f"CL = {_humanize(cl, 'F')}")
    if extras:
        title += "  •  " + ", ".join(extras)
    _label(ax, 5.5, 4.2, title, fontsize=12, weight="bold", color="#0f172a")

    png, svg = _save(plt, fig, png_path, svg_path)
    return _topology_result(png, svg)


def _topology_result(png, svg):
    return {
        "schematic_png_path": png,
        "schematic_svg_path": svg,
        "schematic_status": "topology_schematic",
        "schematic_failure_reason": None,
    }


def _safe_float(value):
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Lcapy + generic fallback (existing behaviour preserved)
# ---------------------------------------------------------------------------


def _try_lcapy(text: str, png_path: str, svg_path: str) -> dict:
    devices = parse_devices(text)
    if not devices:
        return _failed("no drawable devices found")
    if any(device["kind"] in {"M", "Q"} for device in devices):
        return _failed("MOS/BJT schematic is routed to fallback graph renderer")
    timeout_s = int(os.getenv("I13_SCHEMATIC_LCAPY_TIMEOUT", "8"))
    try:
        _ensure_tex_path()
        from lcapy import Circuit

        def render():
            circuit = Circuit(text)
            circuit.draw(svg_path)
            try:
                circuit.draw(png_path)
            except Exception:
                pass

        _run_with_timeout(render, timeout_s)
        return {
            "schematic_png_path": png_path if os.path.exists(png_path) else None,
            "schematic_svg_path": svg_path if os.path.exists(svg_path) else None,
            "schematic_status": "exact_lcapy",
            "schematic_failure_reason": None,
        }
    except Exception as exc:
        return _failed(str(exc))


def _run_with_timeout(func, timeout_s: int):
    if timeout_s <= 0 or not hasattr(signal, "SIGALRM"):
        return func()

    def handler(signum, frame):
        raise TimeoutError(f"lcapy render exceeded {timeout_s}s")

    old_handler = signal.signal(signal.SIGALRM, handler)
    signal.alarm(timeout_s)
    try:
        return func()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)


def _draw_fallback_graph(text: str, png_path: str, svg_path: str) -> dict:
    devices = parse_devices(text)
    if not devices:
        return _failed("no drawable devices found")
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        from matplotlib.patches import FancyArrowPatch, Rectangle
    except Exception as exc:
        return _failed(f"matplotlib unavailable: {exc}")

    roles = _node_roles(devices)
    fig_w = min(16, max(10, 1.25 * len(devices) + 4))
    fig_h = 7.0
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))
    ax.set_xlim(-1.0, max(8.5, len(devices) * 1.35 + 2.5))
    ax.set_ylim(-3.2, 3.2)
    ax.axis("off")

    right_edge = max(7.5, len(devices) * 1.35 + 1.6)
    _draw_rails(ax, right_edge)
    _draw_io_labels(ax, roles, right_edge)
    _draw_stage_boxes(ax, devices, right_edge, Rectangle)

    x = 0.8
    row_offsets = {0: 0.95, 1: -0.95, 2: 0.0}
    for idx, device in enumerate(devices):
        x += 1.25
        y = row_offsets[idx % 3]
        if _is_supply_device(device):
            _draw_supply(ax, device, x, y)
        elif device["kind"] == "M":
            _draw_mos_fallback(ax, device, x, y)
        elif device["kind"] in {"R", "C", "L"}:
            _draw_passive(ax, device, x, y)
        elif device["kind"] in {"V", "I"}:
            _draw_source(ax, device, x, y)
        else:
            _draw_block_device(ax, device, x, y)

    ax.add_patch(FancyArrowPatch((0.15, 0), (right_edge - 0.25, 0), arrowstyle="->", mutation_scale=15, linewidth=1.4, color="#2563eb", alpha=0.8))
    ax.text(0.5, 0.97, "Generic schematic fallback (left-to-right SPICE realization)", transform=ax.transAxes, ha="center", va="top", fontsize=12, weight="bold", color="#111827")
    ax.text(0.5, 0.04, "Used when no topology renderer matches and Lcapy/LaTeX is unavailable.", transform=ax.transAxes, ha="center", va="bottom", fontsize=9, color="#475569")
    Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=160, bbox_inches="tight")
    fig.savefig(svg_path, bbox_inches="tight")
    plt.close(fig)
    return {
        "schematic_png_path": png_path if os.path.exists(png_path) else None,
        "schematic_svg_path": svg_path if os.path.exists(svg_path) else None,
        "schematic_status": "fallback_graph",
        "schematic_failure_reason": None,
    }


def _node_roles(devices: list[dict]) -> dict:
    nodes = {node.lower(): node for device in devices for node in device["nodes"]}
    def first(candidates, default):
        for candidate in candidates:
            if candidate in nodes:
                return nodes[candidate]
        return default

    return {
        "input": first(["in", "vin", "inp", "vinp", "gate"], "IN"),
        "output": first(["out", "vout", "outp", "drain"], "OUT"),
        "vdd": first(["vdd", "vcc", "vdda"], "VDD"),
        "vss": first(["vss", "vee", "gnd", "0"], "0"),
    }


def _draw_rails(ax, right_edge: float):
    ax.plot([0.25, right_edge], [2.35, 2.35], color="#b45309", linewidth=2.4)
    ax.plot([0.25, right_edge], [-2.35, -2.35], color="#334155", linewidth=2.4)
    ax.text(0.0, 2.35, "VDD", ha="right", va="center", fontsize=10, weight="bold", color="#92400e")
    ax.text(0.0, -2.35, "VSS / GND", ha="right", va="center", fontsize=10, weight="bold", color="#334155")


def _draw_io_labels(ax, roles: dict, right_edge: float):
    ax.scatter([0.25], [0], s=120, color="#dbeafe", edgecolors="#1d4ed8", linewidths=1.5, zorder=4)
    ax.scatter([right_edge], [0], s=120, color="#dcfce7", edgecolors="#15803d", linewidths=1.5, zorder=4)
    ax.text(0.25, -0.28, f"input\n{roles['input']}", ha="center", va="top", fontsize=9, color="#1e3a8a")
    ax.text(right_edge, -0.28, f"output\n{roles['output']}", ha="center", va="top", fontsize=9, color="#166534")


def _draw_stage_boxes(ax, devices: list[dict], right_edge: float, Rectangle):
    has_mos = any(device["kind"] == "M" for device in devices)
    has_passive = any(device["kind"] in {"R", "C", "L"} for device in devices)
    labels = []
    if has_mos:
        labels.append("Stage 1: gain / active device")
    if len([device for device in devices if device["kind"] == "M"]) > 1:
        labels.append("Stage 2: bias / buffer devices")
    if has_passive:
        labels.append("Stage 3: load / filter network")
    if not labels:
        labels = ["Stage 1: source", "Stage 2: network", "Stage 3: load"]
    width = max(1.8, (right_edge - 1.2) / len(labels))
    x0 = 0.75
    for idx, label in enumerate(labels[:3]):
        ax.add_patch(Rectangle((x0 + idx * width, -2.75), width - 0.15, 5.45, fill=False, edgecolor="#cbd5e1", linewidth=1.0, linestyle="--"))
        ax.text(x0 + idx * width + 0.08, 2.62, label, ha="left", va="bottom", fontsize=8.5, color="#475569")


def _is_supply_device(device: dict) -> bool:
    name = device.get("name", "").lower()
    nodes = {node.lower() for node in device.get("nodes") or []}
    return device.get("kind") == "V" and ("vdd" in name or "vdd" in nodes or "vcc" in nodes)


def _draw_supply(ax, device: dict, x: float, y: float):
    ax.plot([x, x], [2.35, 1.25], color="#b45309", linewidth=1.6)
    ax.add_patch(plt_circle(ax, (x, 1.0), 0.25, "#fff7ed", "#b45309"))
    ax.text(x, 0.58, f"{device['name']} supply\n{device.get('value', '')}", ha="center", va="top", fontsize=8.5, color="#7c2d12")


def _draw_source(ax, device: dict, x: float, y: float):
    ax.add_patch(plt_circle(ax, (x, y), 0.33, "#eff6ff", "#1d4ed8"))
    ax.plot([x - 0.55, x - 0.33], [y, y], color="#475569", linewidth=1.2)
    ax.plot([x + 0.33, x + 0.55], [y, y], color="#475569", linewidth=1.2)
    ax.text(x, y, "src", ha="center", va="center", fontsize=7.5, color="#1e40af")
    ax.text(x, y - 0.52, _device_label(device), ha="center", va="top", fontsize=8.5, color="#1e3a8a")


def _draw_passive(ax, device: dict, x: float, y: float):
    color = {"R": "#7c2d12", "C": "#155e75", "L": "#6d28d9"}.get(device["kind"], "#111827")
    ax.plot([x - 0.62, x - 0.34], [y, y], color="#475569", linewidth=1.2)
    ax.plot([x + 0.34, x + 0.62], [y, y], color="#475569", linewidth=1.2)
    if device["kind"] == "R":
        ax.add_patch(plt_rect(ax, (x - 0.34, y - 0.16), 0.68, 0.32, "#fff7ed", color))
    elif device["kind"] == "C":
        ax.plot([x - 0.12, x - 0.12], [y - 0.34, y + 0.34], color=color, linewidth=2)
        ax.plot([x + 0.12, x + 0.12], [y - 0.34, y + 0.34], color=color, linewidth=2)
    else:
        for offset in (-0.18, 0.0, 0.18):
            ax.add_patch(plt_circle(ax, (x + offset, y), 0.12, "none", color))
    ax.text(x, y - 0.48, _device_label(device), ha="center", va="top", fontsize=8.5, color=color)


def _draw_mos_fallback(ax, device: dict, x: float, y: float):
    ax.add_patch(plt_rect(ax, (x - 0.36, y - 0.48), 0.72, 0.96, "#f8fafc", "#334155"))
    ax.plot([x - 0.58, x - 0.38], [y, y], color="#2563eb", linewidth=1.4)
    ax.plot([x, x], [y + 0.48, min(2.35, y + 0.96)], color="#b45309", linewidth=1.4)
    ax.plot([x, x], [y - 0.48, max(-2.35, y - 0.96)], color="#334155", linewidth=1.4)
    ax.text(x - 0.66, y, "G", ha="right", va="center", fontsize=8, color="#1d4ed8")
    ax.text(x + 0.08, y + 0.75, "D", ha="left", va="center", fontsize=8, color="#92400e")
    ax.text(x + 0.08, y - 0.75, "S", ha="left", va="center", fontsize=8, color="#334155")
    ax.text(x, y, _device_label(device), ha="center", va="center", fontsize=8.3, color="#0f172a")


def _draw_block_device(ax, device: dict, x: float, y: float):
    ax.add_patch(plt_rect(ax, (x - 0.45, y - 0.32), 0.9, 0.64, "#eef2ff", "#4338ca"))
    ax.text(x, y, _device_label(device), ha="center", va="center", fontsize=8.2, color="#312e81")


def plt_rect(ax, xy, width, height, face, edge):
    from matplotlib.patches import Rectangle

    patch = Rectangle(xy, width, height, facecolor=face, edgecolor=edge, linewidth=1.4)
    return patch


def plt_circle(ax, xy, radius, face, edge):
    from matplotlib.patches import Circle

    patch = Circle(xy, radius, facecolor=face, edgecolor=edge, linewidth=1.4)
    return patch


def _device_label(device: dict) -> str:
    value = device.get("value") or ""
    if device.get("kind") == "M":
        params = " ".join(device.get("params") or [])
        wl = _mos_wl_label(params)
        model = "PMOS" if "pmos" in value.lower() else "NMOS" if "nmos" in value.lower() else value
        return f"{device['name']} {model}\n{wl}".strip()
    return f"{device['name']}\n{value}"


def _mos_wl_label(params: str) -> str:
    w = re.search(r"\bw\s*=\s*([^\s]+)", params, re.IGNORECASE)
    l = re.search(r"\bl\s*=\s*([^\s]+)", params, re.IGNORECASE)
    parts = []
    if w:
        parts.append(f"W={w.group(1)}")
    if l:
        parts.append(f"L={l.group(1)}")
    return " ".join(parts) or "W/L sized"


def _failed(reason: str) -> dict:
    return {
        "schematic_png_path": None,
        "schematic_svg_path": None,
        "schematic_status": "failed",
        "schematic_failure_reason": reason,
    }


def main():
    parser = argparse.ArgumentParser(description="Generate a schematic image from generated.sp")
    parser.add_argument("netlist", help="Path to generated.sp")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument("--topology", default=None, help="Optional topology hint for topology-specific rendering.")
    args = parser.parse_args()
    result = generate_schematic(args.netlist, args.out, topology=args.topology)
    metadata_path = str(Path(args.out).with_name("schematic_metadata.json"))
    Path(metadata_path).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
