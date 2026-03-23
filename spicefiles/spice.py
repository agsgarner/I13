import subprocess
import re

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
            except ValueError:
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

file = input("Enter SPICE file: ")
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

print("\nRegion Check:")
if mos["Vds"] is not None and mos["Vgs"] is not None and mos["Vth"] is not None:
    if mos["Vds"] > (mos["Vgs"] - mos["Vth"]):
        print("  Saturation")
    else:
        print("  Not in saturation")
else:
    print("  Could not determine region")
