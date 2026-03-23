* NMOS test circuit

Vdd vdd 0 1.8
Vin in 0 DC 0.9

M1 out in 0 0 NMOS L=180n W=1u
R1 vdd out 10k

.model NMOS NMOS (VTO=0.5 KP=100u)

.op
.end
