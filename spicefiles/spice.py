import subprocess
import re


def run_spice(file):
    result = subprocess.run(
        ["/opt/homebrew/bin/ngspice", "-b", file],
        capture_output=True,
        text=True
    )
    return result.stdout

# extract node voltages
def extract_voltages(output):
    matches = re.findall(r"\n\s*(\w+)\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)", output)
    return {name: float(val) for name, val in matches}

# extract MOS parameters
def extract_mos(output):
    def get(pattern):
        m = re.search(pattern, output, re.IGNORECASE)
        return float(m.group(1)) if m else None

    return {
        "Id": get(r"\bid\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
        "Vgs": get(r"\bvgs\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
        "Vds": get(r"\bvds\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
        "Vth": get(r"\bvon\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)"),
    }

# main test
output = run_spice("mosfet_test.sp")

voltages = extract_voltages(output)
mos = extract_mos(output)

print("Voltages:", voltages)
print("MOS data:", mos)


if mos["Vds"] and mos["Vgs"] and mos["Vth"]:
    if mos["Vds"] > (mos["Vgs"] - mos["Vth"]):
        print("Saturation")
    else:
        print("Not in saturation")
