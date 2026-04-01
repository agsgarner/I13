import subprocess
import re
import json
import math

def run_spice(file):
    result = subprocess.run(
        ["/opt/homebrew/bin/ngspice", "-b", file],
        capture_output=True,
        text=True
    )
    return result.stdout

def extract_voltages(output):
    section = re.search(r"Node\s+Voltage.*?\n(.*?)(?:\n\n|\Z)", output, re.DOTALL)

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

def extract_ac_data(output):
    freqs = []
    mags = []

    lines = output.splitlines()
    ac_section = False

    for line in lines:
        if "Index" in line and "vm(out)" in line:
            ac_section = True
            continue

        if ac_section:
            parts = line.split()
            if len(parts) < 3:
                continue
            try:
                freq = float(parts[1])
                mag = float(parts[2])
                freqs.append(freq)
                mags.append(mag)
            except:
                continue

    return freqs, mags

def calculate_gain_bandwidth(freqs, mags):
    if not freqs or not mags:
        return None, None, None

    dc_gain_vv = mags[0]
    dc_gain_db = 20 * math.log10(dc_gain_vv) if dc_gain_vv > 0 else None

    target = dc_gain_vv / math.sqrt(2)
    bandwidth = None

    for i in range(1, len(mags)):
        if mags[i] <= target:
            bandwidth = freqs[i]
            break

    return dc_gain_vv, dc_gain_db, bandwidth

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

mode = input("Type 'generate' to auto-generate OR 'file' to choose a file: ").strip().lower()

if mode == "file":
    file = input("Enter SPICE file name (e.g., mosfet_test.sp or common_source.sp): ").strip()
    netlist = open(file).read()
elif mode == "generate":
    spec = "Design circuit with Vout ≈ 1.2V"
    file, netlist = generate_circuit()
else:
    print("Invalid option. Type only 'generate' or 'file'.")
    raise SystemExit

output = run_spice(file)

print("\nRaw SPICE Output:\n")
print(output)

voltages = extract_voltages(output)
mos = extract_mos(output)
freqs, mags = extract_ac_data(output)
dc_gain_vv, dc_gain_db, bandwidth = calculate_gain_bandwidth(freqs, mags)

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
if mos["Vds"] is not None and mos["Vgs"] is not None and mos["Vth"] is not None:
    if mos["Vgs"] > mos["Vth"] and mos["Vds"] > (mos["Vgs"] - mos["Vth"]):
        valid = True

print("\nRegion Check:")
print("  Saturation" if valid else "  Not in saturation or transistor is off")

print("\nAC Analysis:")
if dc_gain_vv is not None:
    print(f"  DC Gain: {dc_gain_vv:.4f} V/V")
    print(f"  DC Gain: {dc_gain_db:.2f} dB")
else:
    print("  DC Gain: not found")

if bandwidth is not None:
    print(f"  Bandwidth (-3 dB): {bandwidth:.2f} Hz")
else:
    print("  Bandwidth (-3 dB): not found")

if valid:
    save_to_dataset("Custom spec", netlist)
    print("\nSaved to dataset.jsonl")
