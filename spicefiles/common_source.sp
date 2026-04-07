* working common-source amplifier

Vdd vdd 0 DC 1.8
Vin in 0 DC 0.7 AC 1

Rd vdd out 5k
M1 out in 0 0 NMOS L=180n W=5u

.model NMOS NMOS (VTO=0.5 KP=100u LAMBDA=0.02)

.control
op
ac dec 20 1 1e9
C1 out 0 1p
print v(out) v(in)
print vm(out)
.endc

.end
