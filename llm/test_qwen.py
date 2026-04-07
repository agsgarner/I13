from llm.qwen_client import QwenLLM

llm = QwenLLM(model="qwen-plus")

prompt = """
Design a common-source amplifier.
Supply voltage: 1.8 V
Target gain: about 20 dB
Target bandwidth: at least 1 MHz
Power limit: 2 mW

Return only a valid ngspice netlist ending with .end
"""

print(llm.generate(prompt))
