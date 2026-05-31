"""
megaLoopback.py — РОБАСТНИЙ форк: БАЙТ = одна нота з 256 (256-FSK), не біти.
Грає ОДНУ частоту за символ; її номер (0..255) = байт. Детект = «яка з 256 частот найгучніша».

Чому так (варіант B): чиста ЕНЕРГІЯ -> імунне до дрейфу рівня І фази. Між двома телефонами
(різні кварци -> частотний зсув убиває когерентний OFDM нашого loopback.py) FSK виживає:
зсув у кілька Гц лише трохи змістить пік, сусідні біни його не переб'ють. Це міст до 2 пристроїв.

Ціна: повільно (1 байт/символ ~285 б/с проти 8000 у loopback). Робастність замість швидкості.
Reed-Solomon на байтах -> виправляє биті символи. Гнучкий вхід input.* як у loopback.

Версія: 0.1
"""
import os, glob
import numpy as np
import sounddevice as sd
from reedsolo import RSCodec

VERSION = "0.1"
SR      = 44100
M       = 256                       # 256 частот = 1 байт/символ
F0      = 800                       # низ смуги FSK
STEP    = 40                        # крок між тонами (Габор: STEP×TACT ≥ ~1.1)
TACT    = 0.030                     # тривалість одного тону
FADE_FRAC = 0.15
PRE_F0, PRE_F1, PRE_DUR = 1000, 6000, 0.20   # ЧИРП-маячок: гострий синк
RS_PARITY = 40                      # RS(40) -> виправляє 20 битих байтів на 255-блок

FREQS = [F0 + i * STEP for i in range(M)]     # 256 тонів: 800..10840 Гц (у межах Найквіста)
n = int(SR * TACT)
fade = max(8, int(FADE_FRAC * n))
t_n = np.linspace(0, TACT, n, endpoint=False)
SIN = [np.sin(2 * np.pi * f * t_n) for f in FREQS]
COS = [np.cos(2 * np.pi * f * t_n) for f in FREQS]
ENV = np.ones(n); ENV[:fade] = np.linspace(0, 1, fade); ENV[-fade:] = np.linspace(1, 0, fade)

HERE = os.path.dirname(os.path.abspath(__file__))
IO   = os.path.join(HERE, "матеріали", "io")
_inp = [g for g in glob.glob(os.path.join(IO, "input.*")) if not g.endswith(".npz")]
IN_PATH  = max(_inp, key=os.path.getmtime) if _inp else os.path.join(IO, "input.png")
_ext = os.path.splitext(IN_PATH)[1] or ".png"
OUT_PATH = os.path.join(IO, "output" + _ext)
RES = os.path.join(IO, "mega_result.txt")

_lines = []
def out(s=""):
    print(s); _lines.append(s)

def chirp(dur):
    m = int(SR * dur); k = (PRE_F1 - PRE_F0) / dur; t = np.arange(m) / SR
    return np.sin(2 * np.pi * (PRE_F0 * t + 0.5 * k * t * t))

preamble = chirp(PRE_DUR)
preN = len(preamble)

def tone(byte):
    return SIN[byte] * ENV

def safe(buf):
    s = buf * 0.7; pk = float(np.max(np.abs(s)))
    return s * (0.95 / pk) if pk > 0.95 else s

# ---------- ДАНІ + RS ----------
out(f"ВХІД: {os.path.basename(IN_PATH)} {os.path.getsize(IN_PATH)}B")
data = open(IN_PATH, "rb").read()
rsc = RSCodec(RS_PARITY)
tx = bytes(rsc.encode(data))                       # кожен символ = 1 байт
est = (len(tx) * TACT + PRE_DUR)
out(f"megaLoopback v{VERSION} | 256-FSK | {len(data)}B +{len(tx)-len(data)}RS = {len(tx)} тонів | "
    f"~{est:.0f}с | {1/TACT:.0f} байт/с ({8/TACT:.0f} б/с) — тиша")

# ---------- TX ----------
sig = np.concatenate([tone(b) for b in tx])
play_buf = safe(np.concatenate([preamble, sig, np.zeros(int(SR * 0.4))]))
rec = sd.playrec(play_buf, SR, channels=1); sd.wait()
rec = rec[:, 0]
out(f"пік RX: {float(np.max(np.abs(rec))):.3f}")

# ---------- СИНК: нормована matched-filter кореляція з чирпом ----------
ps = np.concatenate([[0.0], np.cumsum(rec * rec)])
lim = len(rec) - preN - len(tx) * n
best, bestv = 0, -1.0
step = 4
for p in range(0, max(1, lim), step):
    s = float(np.dot(rec[p:p+preN], preamble))
    e = ps[p+preN] - ps[p]
    sc = abs(s) / np.sqrt(e) if e > 1e-9 else 0.0
    if sc > bestv: bestv, best = sc, p
for p in range(max(0, best-step), best+step):       # уточнення
    s = float(np.dot(rec[p:p+preN], preamble)); e = ps[p+preN] - ps[p]
    sc = abs(s) / np.sqrt(e) if e > 1e-9 else 0.0
    if sc > bestv: bestv, best = sc, p
data_at = best + preN
out(f"синк: pre@{best} score={bestv:.1f}")

# ---------- RX: argmax по 256 тонах на символ ----------
got = bytearray()
for k in range(len(tx)):
    seg = rec[data_at + k*n : data_at + (k+1)*n]
    if len(seg) < n: seg = np.pad(seg, (0, n - len(seg)))
    # магнітуда |I+jQ| кожного тону -> найгучніший = байт
    best_b, best_mag = 0, -1.0
    for b in range(M):
        mag = np.hypot(np.dot(seg, SIN[b]), np.dot(seg, COS[b]))
        if mag > best_mag: best_mag, best_b = mag, b
    got.append(best_b)

raw_err = sum(1 for a, b in zip(tx, got) if a != b)
out(f"сирих символів-помилок: {raw_err}/{len(tx)} ({100*raw_err/max(len(tx),1):.1f}%)")
try:
    rec_data = bytes(rsc.decode(bytes(got))[0])
    open(OUT_PATH, "wb").write(rec_data)
    status = "✅ ІДЕНТИЧНИЙ" if rec_data == data else "⚠️ не збігся"
except Exception:
    status = "❌ RS не витягнув"
out(f"RS({RS_PARITY}) виправляє {RS_PARITY//2}/блок | {status}")

with open(RES, "w", encoding="utf-8") as fh:
    fh.write("\n".join(_lines) + "\n")
