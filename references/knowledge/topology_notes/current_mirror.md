Title: Current Mirror Family Notes
Schema: topology_note
Content-Type: topology_note
Topologies: current_mirror, cascode_current_mirror, wide_swing_current_mirror, wilson_current_mirror, widlar_current_mirror
Tags: bias, current_copy, mirror, compliance
Summary: Start with the simple mirror for baseline bias generation, then step into cascode, wide-swing, Wilson, or Widlar variants as output resistance, headroom, or low-current behavior become dominant.
Selection-Signals: bias branch, current copy, output resistance, compliance window, low current generation
Cautions: compliance headroom, Vov stacking, mismatch sensitivity, output resistance assumptions

# Current Mirror Notes

The simple mirror is the safest first-pass option.
Cascode mirror improves output resistance.
Wide-swing mirror helps when compliance is tight.
Wilson mirror prioritizes copy accuracy.
Widlar mirror is useful when the target current is small relative to available device area.
