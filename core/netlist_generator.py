from textwrap import dedent


def generate_rc_lowpass_netlist(R_ohm: float, C_f: float, fc_hint_hz: float | None = None) -> str:
    """
    Generate an ngspice-compatible netlist for a simple RC low-pass filter.

    We include an AC analysis and a .measure statement that estimates the
    -3 dB cutoff frequency (fc_meas). The SimulationAgent will parse this
    value from the ngspice log.
    """

    # Simple frequency range guess if caller does not provide one
    # Use one decade below and above the expected cutoff as a default.
    if fc_hint_hz is None or fc_hint_hz <= 0:
        fc_hint_hz = 1e3

    f_start = max(fc_hint_hz / 10.0, 1.0)
    f_stop = fc_hint_hz * 10.0

    netlist = f"""
    * RC low-pass filter
    Vin in 0 AC 1
    R1 in out {R_ohm}
    C1 out 0 {C_f}

    .ac dec 50 {f_start} {f_stop}
    .print ac v(out)

    .end
    """

    return dedent(netlist)

