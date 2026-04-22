Title: Common-Source Resistive Load Notes
Schema: topology_note
Content-Type: topology_note
Topologies: common_source_res_load, source_degenerated_cs, common_source_active_load
Tags: amplifier, gain_stage, single_stage, moderate_gain
Summary: Use these stages for simple first-pass gain blocks when a single-ended voltage amplifier is enough and headroom is available.
Selection-Signals: moderate gain, simple demo, single-ended amplification, explicit load resistance
Cautions: output swing vs resistor drop, bias current vs power budget, Miller bandwidth tradeoff

# Common-Source Resistive Load Notes

A common-source stage is a strong default when we need a compact first-pass voltage gain block with readable sizing equations.

Choose source degeneration when linearity matters more than raw gain.
Choose active loads when resistor area or higher effective load resistance matters.
