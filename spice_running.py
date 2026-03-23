import subprocess
import re

result = subprocess.run(
    ["/opt/homebrew/bin/ngspice", "-b", "mosfet_test.sp"],
    capture_output=True,
    text=True
)

output = result.stdout

def extract(pattern):
    match = re.search(pattern, output, re.IGNORECASE)
    return float(match.group(1)) if match else None

vout = extract(r"\bout\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)")
id_val = extract(r"\bid\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)")
vgs = extract(r"\bvgs\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)")
vds = extract(r"\bvds\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)")
vth = extract(r"\bvon\s+([+-]?\d*\.?\d+(?:e[+-]?\d+)?)")

print("Vout:", vout)
print("Id:", id_val)
print("Vgs:", vgs)
print("Vds:", vds)
print("Vth:", vth)

#validating
if vds and vgs and vth:
    if vds > (vgs - vth):
        print("Saturation")
    else:
        print("Not in saturation")
