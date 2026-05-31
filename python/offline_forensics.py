"""
offline_forensics.py — РОЗКОПАТИ бад-момент на реальному записі (dump.npz).
Маємо і data_tx (що грали) і data_rx (що записали) -> міряємо ЗСУВ ТАЙМІНГУ напряму:
чи семпл-клок дрейфує за передачу (-> ресемплер як в amodem), чи момент просто шумний (-> ARQ).
Версія: 0.001
"""
import os
import numpy as np
from numpy.fft import rfft, irfft

d = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "матеріали", "io", "dump.npz"))
tx = d["data_tx"].astype(float); rx = d["data_rx"].astype(float)
SR = int(d["SR"]); BIT = float(d["BIT"]); n = int(SR * BIT)
print(f"tx {len(tx)} | rx {len(rx)} | n={n} семпл/символ | {len(rx)/SR:.1f}с")

def lag_in(window_rx, template_tx):
    """зсув template_tx всередині window_rx через FFT-кореляцію (пік)."""
    N = 1
    L = len(window_rx) + len(template_tx)
    while N < L: N <<= 1
    c = irfft(rfft(window_rx, N) * np.conj(rfft(template_tx, N)), N)
    return int(np.argmax(c[:len(window_rx)]))

# 1) ГЛОБАЛЬНИЙ зсув: де tx починається в rx (груба затримка playrec)
W = 8 * n
g = lag_in(rx[:W*6], tx[:W])        # шукаємо початок tx у перших ~48 символах rx
print(f"глобальна затримка playrec ≈ {g} семпл ({g/SR*1000:.1f} мс)")

# 2) ЛОКАЛЬНИЙ зсув РАНО vs ПІЗНО: беремо шматок tx з початку і з кінця сигналу,
#    шукаємо де КОЖЕН лягає в rx -> різниця = накопичений дрейф семпл-клоку.
sig_len = len(tx)
probes = [0.15, 0.35, 0.55, 0.75, 0.92]   # позиції вздовж передачі
print("\nдрейф таймінгу вздовж передачі (зсув tx-шматка в rx відносно глобального):")
lags = []
for frac in probes:
    pos = int(frac * (sig_len - W))
    if pos < 0: continue
    # шукаємо tx[pos:pos+W] у вікні rx навколо очікуваного g+pos
    exp = g + pos
    lo = max(0, exp - 2000); hi = min(len(rx), exp + W + 2000)
    rel = lag_in(rx[lo:hi], tx[pos:pos+W])
    actual = lo + rel
    drift = actual - exp
    lags.append((frac, drift))
    print(f"  @{frac*100:3.0f}% (символ ~{pos//n:4d}): зсув {drift:+5d} семпл vs очікуваного")

if len(lags) >= 2:
    d0 = lags[0][1]; d1 = lags[-1][1]
    nsym = sig_len // n
    total = d1 - d0
    print(f"\nНАКОПИЧЕНИЙ дрейф старт->кінець: {total:+d} семпл за ~{nsym} символів")
    print(f"  = {total/max(nsym,1):+.3f} семпл/символ")
    if abs(total) >= 2:
        print(f"  >>> КЛОК ДРЕЙФУЄ. На 20кГц {abs(total)} семпл = {abs(total)*20000/SR*360:.0f}° повний скрамбл фази.")
        print(f"  >>> ЛІК: ресемплер/PLL клоку (фіча №2 з amodem) — НЕ просто шумний момент.")
    else:
        print(f"  >>> клок СТАБІЛЬНИЙ (<2 семпл). 8% — це справді ШУМНИЙ момент -> ARQ, не таймінг.")
