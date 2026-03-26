import subprocess
import re
import json

def run_spice(file):
    result = subprocess.run(
        ["/opt/homebrew/bin/ngspice", "-b", file],
        capture_output=True,
        text=True
    )
    return result.stdout

def extract_voltages(output):
    section = re.search(r"Node\s+Voltage.*?\n(.*?)\n\n", output, re.DOTALL)

    voltages = {}
    if section:
        lines = section.group(1).split("\n")
        for line in lines:
            parts = line.split()
            if len(parts) != 2:
                continue
            name, val = parts
            if "-" in val:
                continue
            try:
                voltages[name] = float(val)
            except:
                continue
    return voltages

def extract_mos(output):
    def get(pattern):
        match = re.search(pattern, output, re.IGNORECASE)
        return float(match.group(1)) if match else None

    return {
        "Id": get(r"\bid\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
        "Vgs": get(r"\bvgs\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
        "Vds": get(r"\bvds\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
        "Vth": get(r"\bvon\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
    }

def generate_circuit(filename="generated.sp"):
    netlist = """* generated circuit
Vdd vdd 0 1.8
Vin in 0 DC 0.9
M1 out in 0 0 NMOS L=180n W=1u
R1 vdd out 10k
.model NMOS NMOS (VTO=0.5 KP=100u)
.op
.print op v(out)
.end
"""
    with open(filename, "w") as f:
        f.write(netlist)

    return filename, netlist

def save_to_dataset(spec, netlist):
    entry = {
        "messages": [
            {"role": "user", "content": spec},
            {"role": "assistant", "content": netlist}
        ]
    }

    with open("dataset.jsonl", "a") as f:
        f.write(json.dumps(entry) + "\n")

# ===== MAIN =====

mode = input("Type 'generate' to auto-generate OR 'file' to choose a file: ").strip().lower()

if mode == "file":
    file = input("Enter SPICE file name (e.g., mosfet_test.sp): ").strip()
    netlist = open(file).read()
else:
    spec = "Design circuit with Vout ≈ 1.2V"
    file, netlist = generate_circuit()

output = run_spice(file)

voltages = extract_voltages(output)
mos = extract_mos(output)

print("\nVoltages:")
for name, value in voltages.items():
    print(f"  {name}: {value:.4f} V")

print("\nMOS Data:")
if mos["Id"] is not None:
    print(f"  Id: {mos['Id']:.6e} A")
if mos["Vgs"] is not None:
    print(f"  Vgs: {mos['Vgs']:.3f} V")
if mos["Vds"] is not None:
    print(f"  Vds: {mos['Vds']:.3f} V")
if mos["Vth"] is not None:
    print(f"  Vth: {mos['Vth']:.3f} V")

valid = False
if mos["Vds"] and mos["Vgs"] and mos["Vth"]:
    if mos["Vds"] > (mos["Vgs"] - mos["Vth"]):
        valid = True

print("\nRegion Check:")
print("  Saturation" if valid else "  Not in saturation")

if valid:
    save_to_dataset("Custom spec", netlist)
    print("\nSaved to dataset.jsonl")
