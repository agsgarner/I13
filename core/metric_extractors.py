import math
import re


def _series_xy(data):
    xs = [float(value) for value in ((data or {}).get("x") or [])]
    ys = [float(value) for value in ((data or {}).get("y") or [])]
    points = min(len(xs), len(ys))
    return xs[:points], ys[:points]


def _interpolate_x_for_target(x1, y1, x2, y2, target, log_x=False):
    x1 = float(x1)
    x2 = float(x2)
    y1 = float(y1)
    y2 = float(y2)
    target = float(target)

    if abs(y2 - y1) < 1e-30:
        return x2

    frac = (target - y1) / (y2 - y1)
    frac = max(0.0, min(1.0, frac))

    if log_x:
        lx1 = math.log10(max(x1, 1e-30))
        lx2 = math.log10(max(x2, 1e-30))
        return 10.0 ** (lx1 + frac * (lx2 - lx1))
    return x1 + frac * (x2 - x1)


def _interpolate_y_for_x(x1, y1, x2, y2, target_x, log_x=False):
    x1 = float(x1)
    x2 = float(x2)
    y1 = float(y1)
    y2 = float(y2)
    target_x = float(target_x)

    if log_x:
        x1 = math.log10(max(x1, 1e-30))
        x2 = math.log10(max(x2, 1e-30))
        target_x = math.log10(max(target_x, 1e-30))

    if abs(x2 - x1) < 1e-30:
        return y2
    frac = (target_x - x1) / (x2 - x1)
    frac = max(0.0, min(1.0, frac))
    return y1 + frac * (y2 - y1)


def _crossing_time(xs, ys, target, rising=True):
    if len(xs) < 2 or len(ys) < 2:
        return None

    for idx in range(1, min(len(xs), len(ys))):
        y_prev = float(ys[idx - 1])
        y_cur = float(ys[idx])
        crossed = (y_prev <= target <= y_cur) if rising else (y_prev >= target >= y_cur)
        if crossed:
            return _interpolate_x_for_target(
                xs[idx - 1],
                y_prev,
                xs[idx],
                y_cur,
                target,
                log_x=False,
            )
    return None


def _extract_gain_series(ac_data, input_ac_mag=1.0):
    xs, ys = _series_xy(ac_data)
    if len(xs) < 2 or len(ys) < 2:
        return [], [], []

    input_ac_mag = max(float(input_ac_mag), 1e-20)
    gains = [max(abs(value) / input_ac_mag, 1e-20) for value in ys]
    gains_db = [20.0 * math.log10(value) for value in gains]
    return xs, gains, gains_db


def _unwrap_phase_deg(phases):
    if not phases:
        return []

    unwrapped = [float(phases[0])]
    for phase in phases[1:]:
        value = float(phase)
        prev = unwrapped[-1]
        while (value - prev) > 180.0:
            value -= 360.0
        while (value - prev) < -180.0:
            value += 360.0
        unwrapped.append(value)
    return unwrapped


def extract_phase_margin(ac_data, phase_data, input_ac_mag=1.0):
    xs_mag, gains, _ = _extract_gain_series(ac_data, input_ac_mag=input_ac_mag)
    xs_phase, phases = _series_xy(phase_data)
    if len(xs_mag) < 3 or len(xs_phase) < 3 or len(phases) < 3:
        return None

    unity_hz = None
    for idx in range(1, len(gains)):
        y1 = gains[idx - 1]
        y2 = gains[idx]
        if (y1 >= 1.0 >= y2) or (y1 <= 1.0 <= y2):
            unity_hz = _interpolate_x_for_target(
                xs_mag[idx - 1],
                y1,
                xs_mag[idx],
                y2,
                1.0,
                log_x=True,
            )
            break

    if unity_hz is None:
        return None

    phases = _unwrap_phase_deg(phases)
    phase_at_unity = None
    for idx in range(1, len(xs_phase)):
        x1 = float(xs_phase[idx - 1])
        x2 = float(xs_phase[idx])
        if x1 <= unity_hz <= x2 or x2 <= unity_hz <= x1:
            phase_at_unity = _interpolate_y_for_x(
                x1,
                phases[idx - 1],
                x2,
                phases[idx],
                unity_hz,
                log_x=True,
            )
            break

    if phase_at_unity is None:
        return None

    while phase_at_unity > 0.0:
        phase_at_unity -= 360.0
    while phase_at_unity <= -360.0:
        phase_at_unity += 360.0
    return 180.0 + phase_at_unity


def extract_ac_metrics(ac_data, input_ac_mag=1.0, phase_data=None):
    xs, gains, gains_db = _extract_gain_series(ac_data, input_ac_mag=input_ac_mag)
    metrics = {"sample_count": len(xs)}
    if len(xs) < 3 or len(gains) < 3:
        return metrics

    metrics["gain_db"] = gains_db[0]
    metrics["peak_gain_db"] = max(gains_db)
    peak_idx = max(range(len(gains_db)), key=lambda idx: gains_db[idx])
    metrics["peak_frequency_hz"] = xs[peak_idx]

    target_3db = gains[0] / math.sqrt(2.0)
    for idx in range(1, len(gains)):
        y1 = gains[idx - 1]
        y2 = gains[idx]
        if (y1 >= target_3db >= y2) or (y1 <= target_3db <= y2):
            metrics["bandwidth_hz"] = _interpolate_x_for_target(
                xs[idx - 1],
                y1,
                xs[idx],
                y2,
                target_3db,
                log_x=True,
            )
            break

    for idx in range(1, len(gains)):
        y1 = gains[idx - 1]
        y2 = gains[idx]
        if (y1 >= 1.0 >= y2) or (y1 <= 1.0 <= y2):
            metrics["ugbw_hz"] = _interpolate_x_for_target(
                xs[idx - 1],
                y1,
                xs[idx],
                y2,
                1.0,
                log_x=True,
            )
            break

    if phase_data:
        phase_margin = extract_phase_margin(
            ac_data=ac_data,
            phase_data=phase_data,
            input_ac_mag=input_ac_mag,
        )
        if phase_margin is not None:
            metrics["phase_margin_deg"] = phase_margin

    return metrics


def extract_dc_metrics(dc_data):
    xs, ys = _series_xy(dc_data)
    metrics = {"sample_count": len(xs)}
    if not xs or not ys:
        return metrics

    metrics.update(
        {
            "sweep_start": xs[0],
            "sweep_stop": xs[-1],
            "sweep_span": xs[-1] - xs[0],
            "output_min_v": min(ys),
            "output_max_v": max(ys),
            "output_swing_v": max(ys) - min(ys),
            "output_midpoint_v": 0.5 * (max(ys) + min(ys)),
            "monotonic_non_decreasing": all(ys[idx] >= ys[idx - 1] for idx in range(1, len(ys))),
            "monotonic_non_increasing": all(ys[idx] <= ys[idx - 1] for idx in range(1, len(ys))),
        }
    )
    return metrics


def extract_current_mirror_dc_metrics(dc_data, target_current_a=None, tolerance=0.10):
    metrics = extract_dc_metrics(dc_data)
    xs, ys = _series_xy(dc_data)
    if not xs or not ys:
        return metrics

    abs_currents = [abs(value) for value in ys]
    metrics["iout_max_a"] = max(abs_currents)
    metrics["iout_min_a"] = min(abs_currents)
    metrics["iout_final_a"] = abs_currents[-1]

    if target_current_a is None:
        return metrics

    target_current_a = abs(float(target_current_a))
    lower_bound = max(target_current_a * (1.0 - float(tolerance)), 0.0)
    for idx, current in enumerate(abs_currents):
        if current >= lower_bound:
            metrics["compliance_voltage_v"] = float(xs[idx])
            metrics["iout_at_compliance_a"] = float(current)
            break
    return metrics


def extract_line_regulation_metrics(dc_data):
    metrics = {}
    xs, ys = _series_xy(dc_data)
    if len(xs) < 2 or len(ys) < 2:
        return metrics

    dvin = float(xs[-1]) - float(xs[0])
    if abs(dvin) < 1e-30:
        return metrics

    dvout = float(ys[-1]) - float(ys[0])
    metrics["line_regulation_v_per_v"] = dvout / dvin
    metrics["line_regulation_mv_per_v"] = 1000.0 * metrics["line_regulation_v_per_v"]
    return metrics


def extract_transient_metrics(tran_out_data, tran_in_data=None, tran_outn_data=None):
    tx, vy = _series_xy(tran_out_data)
    metrics = {"sample_count": len(tx)}
    if len(tx) < 3 or len(vy) < 3:
        return metrics

    metrics["output_min_v"] = min(vy)
    metrics["output_max_v"] = max(vy)
    metrics["output_swing_v"] = max(vy) - min(vy)
    metrics["output_final_v"] = vy[-1]

    edge = max(3, len(vy) // 20)
    out_initial = sum(vy[:edge]) / edge
    out_final = sum(vy[-edge:]) / edge
    out_delta = out_final - out_initial
    metrics["out_initial_v"] = out_initial
    metrics["out_final_v"] = out_final
    metrics["out_step_v"] = out_delta

    if tran_in_data:
        _, in_y = _series_xy(tran_in_data)
        if len(in_y) >= edge:
            in_initial = sum(in_y[:edge]) / edge
            in_final = sum(in_y[-edge:]) / edge
            in_delta = in_final - in_initial
            metrics["in_initial_v"] = in_initial
            metrics["in_final_v"] = in_final
            metrics["in_step_v"] = in_delta
            if abs(in_delta) > 1e-12:
                transient_gain = out_delta / in_delta
                metrics["transient_gain_vv"] = transient_gain
                metrics["transient_gain_db"] = 20.0 * math.log10(max(abs(transient_gain), 1e-20))

    direction_rising = out_delta >= 0
    t10 = _crossing_time(tx, vy, out_initial + 0.10 * out_delta, rising=direction_rising)
    t90 = _crossing_time(tx, vy, out_initial + 0.90 * out_delta, rising=direction_rising)
    if t10 is not None and t90 is not None:
        rise_interval = max(float(t90) - float(t10), 0.0)
        if direction_rising:
            metrics["rise_time_10_90_s"] = rise_interval
        else:
            metrics["fall_time_90_10_s"] = rise_interval

    tol = max(abs(out_delta) * 0.02, 1e-6)
    for idx in range(len(vy)):
        if all(abs(value - out_final) <= tol for value in vy[idx:]):
            metrics["settling_time_s"] = float(tx[idx]) - float(tx[0])
            break

    if abs(out_delta) > 1e-9:
        out_max = max(vy)
        out_min = min(vy)
        if direction_rising:
            metrics["overshoot_pct"] = max(0.0, (out_max - out_final) / abs(out_delta) * 100.0)
            metrics["undershoot_pct"] = max(0.0, (out_initial - out_min) / abs(out_delta) * 100.0)
        else:
            metrics["overshoot_pct"] = max(0.0, (out_final - out_min) / abs(out_delta) * 100.0)
            metrics["undershoot_pct"] = max(0.0, (out_max - out_initial) / abs(out_delta) * 100.0)

    max_slew = None
    for idx in range(1, len(vy)):
        dt = float(tx[idx]) - float(tx[idx - 1])
        if dt <= 0:
            continue
        slew = abs(float(vy[idx]) - float(vy[idx - 1])) / dt
        if max_slew is None or slew > max_slew:
            max_slew = slew
    if max_slew is not None:
        metrics["max_slew_v_per_s"] = max_slew
        metrics["max_slew_v_per_us"] = max_slew / 1e6

    if tran_outn_data:
        _, outn = _series_xy(tran_outn_data)
        samples = min(len(vy), len(outn))
        if samples:
            cm_series = [(vy[idx] + outn[idx]) / 2.0 for idx in range(samples)]
            diff_series = [vy[idx] - outn[idx] for idx in range(samples)]
            metrics["common_mode_final_v"] = cm_series[-1]
            metrics["common_mode_range_v"] = max(cm_series) - min(cm_series)
            metrics["differential_final_v"] = diff_series[-1]
            metrics["differential_swing_v"] = max(diff_series) - min(diff_series)

    return metrics


def extract_noise_metrics_from_text(text):
    metrics = {}
    if not text:
        return metrics

    patterns = {
        "onoise_total_vrms": [
            r"onoise_total\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
            r"total output noise\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
        ],
        "inoise_total_arms": [
            r"inoise_total\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
            r"total input noise\s*=\s*([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)",
        ],
    }

    lowered = str(text).lower()
    for key, candidates in patterns.items():
        for pattern in candidates:
            match = re.search(pattern, lowered, re.IGNORECASE)
            if match:
                metrics[key] = float(match.group(1))
                break
    return metrics
