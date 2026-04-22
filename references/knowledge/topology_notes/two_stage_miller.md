Title: Two-Stage Op-Amp Notes
Schema: topology_note
Content-Type: topology_note
Topologies: two_stage_miller, telescopic_cascode_opamp_core, folded_cascode_opamp, folded_cascode_opamp_core, ldo_error_amp_core
Tags: opamp, compensation, high_gain, driver
Summary: Use these op-amp family templates when the specification asks for gain beyond a single-stage amplifier and when capacitive loads or explicit UGBW goals appear.
Selection-Signals: high gain, ugbw target, phase margin, capacitive load, error amplifier, ota
Cautions: compensation capacitor choice, slew-power tradeoff, output swing, headroom stacking

# Two-Stage and Cascode Op-Amp Notes

Two-stage Miller remains the general-purpose choice for higher gain and moderate load drive.
Folded cascode fits lower-headroom and lower-noise contexts.
Telescopic-style cores favor high intrinsic gain if output swing constraints are manageable.
