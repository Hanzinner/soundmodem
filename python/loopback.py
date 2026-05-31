"""
loopback.py — передати КАРТИНКУ (PNG) звуком через повітря і зберегти копію.
Кладеш поряд input.png (невеликий!). Пише output.png. Мають бути однакові.

ЧЕМПІОН-база v0.3: 5 зон + високий блок 8-12кГц (~96 нот), фазо-вирівняний детектор,
пер-нота поріг √(ON×OFF) з тренування, адаптивний RS. НЕТТО ~2622 б/с (×1.6 від бази).

v0.4: (1) НОІЗ-ГЕЙТ — прелітна тиша міряє шумову підлогу кожної ноти; кидаємо ноти в шумових
гарячих точках (>4× медіани). Карта ночі 31.05: кулер = НИЗЬКОЧАСТОТНИЙ ворог (520=21× медіани),
а хвіст 8-12кГц чистий. Sep одноразовий проґавлював рваний кулер-шум; прямий вимір фону ловить.
Адаптивно до температури: холодний комп (рівний шум) нічого не кидає. (2) ПЕРЕАНКОР порога на
дрейф між проходами (solo-калібр дані/тренування, clamp [0.6,1.7]). Пілоти викинуто — були отрута.

>>> РОБОЧА ТОЧКА (КРИТИЧНО): Microphone level ~50, Boost 0, RX~0.012. <<<
ТИХІШЕ = ЧИСТІШЕ. Високий мік (75+) -> спотворення підсилювача -> високі ноти спайкають -> RS вибухає.
Реальний ворог (ніч 31.05): акустичний шум по хвості 9900-12000, НЕ рівень/дрейф.

Версія: 0.7 (DEV — ФІЧА з amodem: decision-directed PLL фаза-трекінг проти дрейфу-в-часі)
"""

import os
import math
import numpy as np
import sounddevice as sd
from reedsolo import RSCodec

rsc = RSCodec(26)   # макс для 1 блоку (229+26=255) -> виправляє до 13 битих байтів

VERSION   = "0.7"
ILV       = 32            # глибина перемежування (розсіює пачки помилок)

# ---------- НАЛАШТУВАННЯ ----------
SR        = 44100
BIT       = 0.028         # 1000 біт/с; sweep v0.009: 0.028 тримає ≤3 помилки при різкому краї (0.026 = Габор-стіна)
FADE_FRAC = 0.12          # різкість краю ноти: sweep-оптимум (різко=клацання, м'яко=блюр; 0.12 = 2-3 помилки)
PRE_F     = 600
PRE_DUR   = 0.10

ZONES   = [(520, 940), (1720, 2140), (2720, 2940), (3320, 3680), (4320, 4680)]   # 5 зон (sweep: 1714)
HIGH    = (8000, 20000, 80)                          # 8-20к (вісь 1: до Найквіста; 8-16к дало +29% нетто, шукаємо де плато)
EXCLUDE = set()                                      # тренування САМО знаходить мертві ноти
freqs = []
for _lo, _hi in ZONES:
    freqs += list(range(_lo, _hi + 1, 40))
freqs += list(range(HIGH[0], HIGH[1] + 1, HIGH[2]))
freqs = [f for f in freqs if f not in EXCLUDE]        # ~99 несучих кандидатів
FULL_FREQS = list(freqs)                              # повний набір кандидатів (до відбору) — для офлайн-дампу
NCAR  = len(freqs)
t_bit = np.linspace(0, BIT, int(SR * BIT), endpoint=False)
fade  = max(8, int(FADE_FRAC * len(t_bit)))

# pre-emphasis: boost обчислюється адаптивно (прохід 1 міряє АЧХ), старт = 1
GAINS = [1.0] * NCAR

HERE = os.path.dirname(os.path.abspath(__file__))
IO_DIR   = os.path.join(HERE, "матеріали", "io")
# гнучкий вхід: бери будь-який input.* (png/txt/jpg/...) — модем працює з байтами, формат байдужий.
import glob
_inp = [g for g in glob.glob(os.path.join(IO_DIR, "input.*")) if not g.endswith(".npz")]
IN_PATH  = max(_inp, key=os.path.getmtime) if _inp else os.path.join(IO_DIR, "input.png")  # найновіший виграє
_ext = os.path.splitext(IN_PATH)[1] or ".png"
OUT_PATH = os.path.join(IO_DIR, "output" + _ext)   # вихід тим самим розширенням
RESULT_TXT = os.path.join(IO_DIR, "loopback_result.txt")

_lines = []
def out(s=""):
    print(s); _lines.append(s)

# одразу показати ЯКИЙ вхід обрано (newest-wins) — щоб мисмач помітити ДО довгого чекання
try:
    out(f"ВХІД: {os.path.basename(IN_PATH)} {os.path.getsize(IN_PATH)}B  (newest-wins; лиши 1 input.* щоб не плутати)")
except Exception:
    pass


def chord(sym):
    """7-бітний символ -> акорд із потрібних частот."""
    wave = np.zeros(len(t_bit))
    for i in range(NCAR):
        if (sym >> i) & 1:
            wave += GAINS[i] * np.sin(2 * np.pi * freqs[i] * t_bit)
    wave /= NCAR
    env = np.ones(len(wave))
    env[:fade]  = np.linspace(0, 1, fade)
    env[-fade:] = np.linspace(1, 0, fade)
    return wave * env


def raw_tone(freq, dur):
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    return np.sin(2 * np.pi * freq * t)


def bytes_to_symbols(bs):
    """байти -> суцільний потік бітів -> групи по 7 -> символи."""
    bits = []
    for byte in bs:
        for i in range(8):
            bits.append((byte >> i) & 1)
    while len(bits) % NCAR:
        bits.append(0)
    syms = []
    for j in range(0, len(bits), NCAR):
        s = 0
        for i in range(NCAR):
            if bits[j + i]:
                s |= (1 << i)
        syms.append(s)
    return syms


def symbols_to_bytes(syms, nbytes):
    """символи -> потік бітів -> байти (рівно nbytes штук)."""
    bits = []
    for s in syms:
        for i in range(NCAR):
            bits.append((s >> i) & 1)
    out = bytearray()
    for j in range(0, nbytes * 8, 8):
        b = 0
        for i in range(8):
            if j + i < len(bits) and bits[j + i]:
                b |= (1 << i)
        out.append(b)
    return bytes(out)


def interleave(b):
    """перемішати байти, щоб пачка помилок розсіялась по RS-блоках."""
    pad = (-len(b)) % ILV
    a = np.frombuffer(bytes(b) + bytes(pad), dtype=np.uint8).reshape(-1, ILV)
    return a.T.tobytes()


def deinterleave(b, orig_len):
    """зворотне перемішування перед RS-декодуванням."""
    a = np.frombuffer(b, dtype=np.uint8).reshape(ILV, -1)
    return a.T.tobytes()[:orig_len]


# H1: фазо-вирівняна КОГЕРЕНТНА детекція. sin+cos референси, щоб виміряти фазу кожної ноти.
sin_ref = [np.sin(2 * np.pi * f * t_bit) for f in freqs]
cos_ref = [np.cos(2 * np.pi * f * t_bit) for f in freqs]
preamble = raw_tone(PRE_F, PRE_DUR)
n = int(SR * BIT)


def measure_iq(rec_buf):
    """маячок + для кожної ноти: магнітуда |I+jQ| (енергія НЕЗАЛЕЖНО від фази) і фаза atan2(Q,I).
    магнітуда — для GAINS і порога; фаза — щоб повернути референс під реальну фазу каналу."""
    corr = np.correlate(rec_buf, preamble, mode="valid")
    p = int(np.argmax(corr)) + len(preamble)
    mag, phase = [], []
    for i in range(NCAR):
        seg = rec_buf[p + i*n : p + (i+1)*n]
        if len(seg) < n:
            seg = np.pad(seg, (0, n - len(seg)))
        I = np.dot(seg, sin_ref[i]); Q = np.dot(seg, cos_ref[i])
        mag.append(float(np.hypot(I, Q)))
        phase.append(float(np.arctan2(Q, I)))
    return p, mag, phase


def safe(buf):
    """×0.7; лише ПРИТИСКАЄ вниз якщо pre-emphasis вибив за 0.95 (тихого НЕ підсилює)."""
    s = buf * 0.7
    pk = float(np.max(np.abs(s)))
    return s * (0.95 / pk) if pk > 0.95 else s

# ---------- A0. ТИША: шумова підлога кожної ноти ПЕРЕД передачею (кулер — низькочастотний ворог) ----------
# слухаємо ~2с тиші, міряємо середню |I+jQ| кожної ноти на чистому шумі. Рвана природа кулер-шуму
# (то бурхне, то ні) проскакує одноразовий sep на тренуванні -> ловимо її прямим виміром фону.
SILENCE = 2.0
_sil = sd.rec(int(SR * SILENCE), samplerate=SR, channels=1); sd.wait()
_sil = _sil[:, 0].astype(float)
_Wn = max(1, len(_sil) // n)
noise_floor = []
for i in range(NCAR):
    _m = [np.hypot(np.dot(_sil[w*n:(w+1)*n], sin_ref[i]), np.dot(_sil[w*n:(w+1)*n], cos_ref[i])) for w in range(_Wn)]
    noise_floor.append(float(np.mean(_m)))
noise_med = float(np.median(noise_floor))
out(f"тиша: шумова підлога медіана {noise_med:.3f}, макс {max(noise_floor):.3f} (× {max(noise_floor)/max(noise_med,1e-9):.0f})")

# ---------- A. ЗОНД -> pre-emphasis (всі кандидати) ----------
calib = np.concatenate([chord(1 << i) for i in range(NCAR)])      # GAINS=1 поки
probe = np.concatenate([preamble, calib, np.zeros(int(SR * 0.3))])
rec1 = sd.playrec(safe(probe), SR, channels=1); sd.wait()
_, level, _ = measure_iq(rec1[:, 0])
med = float(np.median(level))
for i in range(NCAR):
    GAINS[i] = float(np.clip(med / max(level[i], med * 0.15), 1.0, 4.0))

# ---------- B. ТРЕНУВАННЯ: розділення ON/OFF кожної ноти В КОНТЕКСТІ (метрика з diagnose тест 4) ----------
# передаємо ВІДОМИЙ випадковий патерн повними акордами; для кожної ноти міряємо середню
# магнітуду коли вона мала бути ON vs OFF. Низьке розділення = нота тоне у витоку від інших (як 600).
NTRAIN, MIN_SEP = 50, 1.5   # sep тепер РЕЙЛ (1.5): error-гейт головний (свіп: sep>=2.5 викидав прибуткові ноти)
rng = np.random.default_rng(12345)
tb = (rng.random((NTRAIN, NCAR)) > 0.5).astype(int)
tsyms = [int(sum((1 << i) for i in range(NCAR) if tb[k, i])) for k in range(NTRAIN)]
calibB = np.concatenate([chord(1 << i) for i in range(NCAR)])
sigB   = np.concatenate([chord(s) for s in tsyms])
recB = sd.playrec(safe(np.concatenate([preamble, calibB, sigB, np.zeros(int(SR*0.3))])), SR, channels=1); sd.wait()
recB = recB[:, 0]
pB, calB_lvl, phB = measure_iq(recB)   # calB_lvl: solo-рівень кожної ноти НА ТРЕНУВАННІ (для переанкору)
arefB = [np.cos(phB[i]) * sin_ref[i] + np.sin(phB[i]) * cos_ref[i] for i in range(NCAR)]
dsB = pB + NCAR * n
on_s = np.zeros(NCAR); on_c = np.zeros(NCAR); off_s = np.zeros(NCAR); off_c = np.zeros(NCAR)
for k in range(NTRAIN):
    ch = recB[dsB + k*n : dsB + (k+1)*n]
    if len(ch) < n:
        ch = np.pad(ch, (0, n - len(ch)))
    for i in range(NCAR):
        m = abs(float(np.dot(ch, arefB[i])))
        if tb[k, i]: on_s[i] += m; on_c[i] += 1
        else:        off_s[i] += m; off_c[i] += 1
sep = [(on_s[i]/max(on_c[i],1)) / max(off_s[i]/max(off_c[i],1), 1e-9) for i in range(NCAR)]

# пер-нота ПОМИЛКА на тренуванні — тим самим рішенням що декод (dot>thr, БЕЗ abs). Ловить ноти що
# фліпають ПІД НАВАНТАЖЕННЯМ; sep (середнє ON/OFF) це проґавлює, а це ПРЯМИЙ предиктор дата-помилок.
thr_all = [float(np.sqrt(max(on_s[i]/max(on_c[i],1),1e-9) * max(off_s[i]/max(off_c[i],1),1e-9))) for i in range(NCAR)]
note_err = np.zeros(NCAR)
for k in range(NTRAIN):
    ch = recB[dsB + k*n : dsB + (k+1)*n]
    if len(ch) < n:
        ch = np.pad(ch, (0, n - len(ch)))
    for i in range(NCAR):
        if (1 if float(np.dot(ch, arefB[i])) > thr_all[i] else 0) != int(tb[k, i]):
            note_err[i] += 1
err_rate = [note_err[i] / NTRAIN for i in range(NCAR)]

# ---------- C. ВІДБІР: ГОЛОВНИЙ гейт — ПОМИЛКА під навантаженням. sep/шум лишені інертними рейлами ----------
# offline_sweep проти реального аудіо: error-гейт САМ б'є sep+шум разом (3653 vs 3470) — sep/шум викидали
# прибуткові ноти (низька помилка, але sep<2.5/шум>4×). Error прямо міряє дата-помилку -> поглинає обидва.
# Тому sep->1.5, шум->8× (майже off, лише захист від виродків), а ERR_MAX=3% (4% подвоює parity, валить нетто).
NOISE_MULT = 8.0   # рейл: дроп лише грубо-шумних (error-гейт ловить решту через їхню помилку)
ERR_MAX    = 0.03  # ГОЛОВНИЙ: дроп якщо нота фліпає >3% символів на тренуванні. Оптимум зі свіпу (140 нот, parity 60, нетто 3824)
def keep(i):
    return sep[i] >= MIN_SEP and noise_floor[i] <= NOISE_MULT * noise_med and err_rate[i] <= ERR_MAX
active  = [i for i in range(NCAR) if keep(i)]
drop_sep   = [freqs[i] for i in range(NCAR) if sep[i] < MIN_SEP]
drop_noise = [(freqs[i], f"{noise_floor[i]/max(noise_med,1e-9):.0f}×") for i in range(NCAR)
              if sep[i] >= MIN_SEP and noise_floor[i] > NOISE_MULT * noise_med]
drop_err   = [(freqs[i], f"{err_rate[i]*100:.0f}%") for i in range(NCAR)
              if sep[i] >= MIN_SEP and noise_floor[i] <= NOISE_MULT * noise_med and err_rate[i] > ERR_MAX]
on_tr   = [on_s[i] / max(on_c[i], 1) for i in active]
off_tr  = [off_s[i] / max(off_c[i], 1) for i in active]
thr     = [float(np.sqrt(max(on_tr[j], 1e-9) * max(off_tr[j], 1e-9))) for j in range(len(active))]  # √(ON×OFF) ПЕР-НОТА
freqs   = [freqs[i] for i in active]
NCAR    = len(freqs)
sin_ref = [np.sin(2 * np.pi * f * t_bit) for f in freqs]
cos_ref = [np.cos(2 * np.pi * f * t_bit) for f in freqs]
GAINS   = [GAINS[i] for i in active]
out(f"дроп sep: {drop_sep or 'нема'}")
out(f"дроп ШУМ (кулер): {drop_noise or 'нема'}")
out(f"дроп ПОМИЛКА>{ERR_MAX*100:.0f}%: {drop_err or 'нема'} -> лишилось {NCAR} нот")

# ---------- C3. BIT-LOADING: адаптивний M-PSK. Чисті ноти -> більше біт через БІЛЬШЕ ФАЗ ----------
def _q(x):
    return 0.5 * math.erfc(x / math.sqrt(2))     # P(гаусів шум перетне межу)
# M-PSK симв.помилка ≈ 2·Q(sep·sin(π/M)). Амплітудо-незалежно (спільний кварц -> фаза стабільна).
# QPSK(M=4): sep≥~4. 8-PSK(M=8): фази ближче (45°) -> треба sep≥~7. Беремо НАЙБІЛЬШИЙ порядок під ціль.
# дисконт sep: on/off-ratio ЗАВИЩУЄ справжній фазовий SNR (витік+рейлі-зсув abs) -> реально помилка ~3× моделі.
# Калібр з v0.602 (предкл.1% vs реал.2.9%): sep_eff = sep·0.7 робить і відбір строгішим, і RS-бюджет чесним.
SEP_DISCOUNT = 0.7
def _psk_serr(s, M):
    return 2 * _q(s * SEP_DISCOUNT * math.sin(math.pi / M))
def _gray(v):
    return v ^ (v >> 1)
def _igray(g):
    m = g >> 1
    while m:
        g ^= m; m >>= 1
    return g
PSK_TARGET = 0.01
balloc = []; Mord = []                            # balloc=біт/нота (1 OOK,2 QPSK,3 8-PSK); Mord=порядок PSK (0 якщо OOK)
for j in range(NCAR):
    s = sep[active[j]]
    if err_rate[active[j]] == 0 and _psk_serr(s, 8) < PSK_TARGET:
        balloc.append(3); Mord.append(8)
    elif err_rate[active[j]] == 0 and _psk_serr(s, 4) < PSK_TARGET:
        balloc.append(2); Mord.append(4)
    else:
        balloc.append(1); Mord.append(0)
is_phase = [Mord[j] != 0 for j in range(NCAR)]
ph_serr  = [_psk_serr(sep[active[j]], Mord[j]) if Mord[j] else 0.0 for j in range(NCAR)]
nq = sum(1 for b in balloc if b == 2); n8 = sum(1 for b in balloc if b == 3)
bits_per_sym = sum(balloc)
out(f"bit-loading: {n8} нот -> 8-PSK(3б), {nq} -> QPSK(2б), {NCAR-nq-n8} -> OOK(1б) | {bits_per_sym} біт/символ (ціль помилки {PSK_TARGET*100:.0f}%)")

# ---------- C2. АДАПТИВНИЙ RS: parity з УРАХУВАННЯМ передбаченої фазової помилки (не лише OOK) ----------
ook_be = sum(err_rate[active[j]] for j in range(NCAR) if not is_phase[j])
ph_be  = sum(ph_serr[j]          for j in range(NCAR) if is_phase[j])
# ПІДЛОГА 2%: тренування каже ~0 (overfit), але КАНАЛ НЕСТАЦІОНАРНИЙ — поганий момент дає 2.5% OOK
# при чистому тренуванні (v0.603 ❌). Підлога несе консерватизм; множник ×1.0 (НЕ подвоюємо — підлога+×2
# давали parity 132 overkill при потрібних ~94). Покриває найгірший момент без надлишку.
p_bit = max((ook_be + ph_be) / max(bits_per_sym, 1), 0.02)
bad_per_block = min(255, int(255 * (1 - (1 - p_bit) ** 8)))
parity = int(np.clip(2 * bad_per_block * 1.0 + 16, 24, 230))
rsc = RSCodec(parity)
useful = bits_per_sym / BIT * (255 - parity) / 255
out(f"адаптивний RS: p_bit={p_bit:.3f} (OOK+PSK) -> ~{bad_per_block} битих/блок -> parity {parity}")
out(f"НЕТТО throughput: {useful:.0f} б/с (сирий {bits_per_sym/BIT:.0f} × {255-parity}/255) | OOK-база {NCAR/BIT:.0f}")

def chord_v(vals):
    """акорд: OOK — повна амплітуда якщо vals[i]; M-PSK — завжди ON, фаза = сектор Gray(vals[i])·2π/M."""
    w = np.zeros(n)
    for i in range(NCAR):
        if is_phase[i]:
            theta = _gray(vals[i]) * (2 * math.pi / Mord[i])
            w += GAINS[i] * (math.cos(theta) * sin_ref[i] + math.sin(theta) * cos_ref[i])
        elif vals[i]:
            w += GAINS[i] * sin_ref[i]
    w /= NCAR
    e = np.ones(n); e[:fade] = np.linspace(0, 1, fade); e[-fade:] = np.linspace(1, 0, fade)
    return w * e

def bytes_to_syms_pam(bs):
    """байти -> біти -> символи; нота споживає balloc[i] біт -> значення рівня."""
    bits = []
    for byte in bs:
        for i in range(8): bits.append((byte >> i) & 1)
    while len(bits) % bits_per_sym: bits.append(0)
    syms = []; p = 0
    for _ in range(len(bits) // bits_per_sym):
        vals = []
        for j in range(NCAR):
            v = 0
            for b in range(balloc[j]):
                v |= (bits[p] << b); p += 1
            vals.append(v)
        syms.append(vals)
    return syms

def syms_to_bytes_pam(syms, nbytes):
    """символи (рівні) -> біти -> байти."""
    bits = []
    for vals in syms:
        for j in range(NCAR):
            for b in range(balloc[j]):
                bits.append((int(vals[j]) >> b) & 1)
    o = bytearray()
    for jb in range(0, nbytes * 8, 8):
        by = 0
        for i in range(8):
            if jb + i < len(bits) and bits[jb + i]: by |= (1 << i)
        o.append(by)
    return bytes(o)

# ---------- D. ФАЙЛ + ЗАХИСТ + ПАКУВАННЯ ----------
data = open(IN_PATH, "rb").read()
tx = bytes(rsc.encode(data))
tx_ilv = interleave(tx)               # перемежування проти пачок помилок
symbols = bytes_to_syms_pam(tx_ilv)
est = len(symbols) * BIT
out(f"v{VERSION} | {os.path.basename(IN_PATH)} {len(data)}B +{len(tx)-len(data)}RS | {NCAR} нот ({nq}Q+{n8}×8PSK) {bits_per_sym/BIT:.0f} б/с | ~{est:.0f}с — тиша")

# ---------- 3. ПРОХІД 2: дані з pre-emphasis (calib і signal перебудовані з GAINS) ----------
calib = np.concatenate([chord(1 << i) for i in range(NCAR)])     # калібр — повні одиночні ноти (фаза/рівень)
signal = np.concatenate([chord_v(vals) for vals in symbols])     # дані — багаторівневі акорди (PAM+OOK)
play_buf = safe(np.concatenate([preamble, calib, signal, np.zeros(int(SR * 0.5))]))
peak = float(np.max(np.abs(play_buf)))
out(f"пік TX: {peak:.3f}" + ("  ⚠️ кліп" if peak > 0.95 else "  (ок)"))
rec = sd.playrec(play_buf, SR, channels=1)
sd.wait()
rec = rec[:, 0]
rx_peak = float(np.max(np.abs(rec)))

# ---------- ДАМП для офлайн-тестів (тиша+тренування+дані як РЕАЛЬНЕ аудіо, не уявне) ----------
# NODUMP=1 (ставить channel_sim) -> НЕ писати, щоб сім не затирав реальний запис на диску.
if os.environ.get("NODUMP"):
    out("[дамп пропущено: NODUMP (сім)]")
else:
    try:
        np.savez_compressed(os.path.join(IO_DIR, "dump.npz"),
                            sil=_sil, probe_rx=rec1[:, 0], train_rx=recB, data_rx=rec, data_tx=play_buf,
                            full_freqs=np.array(FULL_FREQS), BIT=BIT, SR=SR, NTRAIN=NTRAIN,
                            PRE_F=PRE_F, PRE_DUR=PRE_DUR)
        out(f"[дамп: матеріали/io/dump.npz — {len(_sil)+len(rec1)+len(recB)+len(rec)} семплів]")
    except Exception as _e:
        out(f"[дамп не вдався: {_e}]")
out(f"пік RX: {rx_peak:.3f}" + ("  ⚠️ КЛІПУЄ — зменш гучність/boost!" if rx_peak > 0.95
     else "  ⚠️ ЗАТИХО (<0.1) — підніми гучність/мікрофон!" if rx_peak < 0.1 else "  (ок)"))

# ---------- 4. КАЛІБР (прохід 2): ФАЗА кожної ноти -> вирівняний референс. Поріг — ПЕР-НОТА (thr з тренування) ----------
pre_at, ref_level, ph = measure_iq(rec)
# фазо-вирівняний референс: aref_i = sin(2πft + φ_i) = cos φ·sin + sin φ·cos.
# dot(chunk, aref) ловить ПОВНУ енергію ноти під її реальною фазою (а не A·cos φ як sin-only),
# і для OFF-ноти це одновісний шум N(0,σ) — без рейлі-зсуву IQ, тобто без глобальних засвітів.
aref = [np.cos(ph[i]) * sin_ref[i] + np.sin(ph[i]) * cos_ref[i] for i in range(NCAR)]
data_start = pre_at + NCAR * n   # дані — після розбитої калібрувальної послідовності

# ---------- ПЕРЕАНКОР: зсунути поріг із тренування на дрейф каналу між проходами ----------
# solo-калібр у ДАНИХ / solo-калібр на ТРЕНУВАННІ = пер-нота зміна підсилення (одноразово, тихо, без пілотів).
# clamp [0.6,1.7]: абсорбуємо помірний дрейф, але не «воскрешаємо» мертву ноту в нуль (то був би засвіт).
drift = [float(np.clip(ref_level[i] / max(calB_lvl[active[i]], 1e-9), 0.6, 1.7)) for i in range(NCAR)]
thr_re = [thr[i] * drift[i] for i in range(NCAR)]
out(f"переанкор: drift {min(drift):.2f}..{max(drift):.2f} (1.00=канал не поплив між проходами)")

# M-PSK дероторація: вимір (I,Q) повертаємо на -φ_i (канальна фаза ноти ph[i]) -> сектор дає біти.
# Амплітудо-незалежно: рішення по КУТУ, не по рівню -> дрейф амплітуди фазу не чіпає.
# >>> ФІЧА з amodem: decision-directed ФАЗА-ТРЕКІНГ. Після рішення міряємо залишкову фазу
#     і слюємо φ_i наживо (PLL) -> коген-детект тримається через ДОВГУ передачу без дослань калібру.
#     Лікує дрейф-у-часі (130KB-фейл) + фундамент під 2 пристрої (частотний зсув кварців).
two_pi = 2 * math.pi
PLL_GAIN = 0.08
phi   = list(ph)                                  # ТРЕКОВАНА фаза (еволюціонує)
qc, qs = [math.cos(p) for p in phi], [math.sin(p) for p in phi]
qc0 = [math.cos(ph[i]) for i in range(NCAR)]      # ФІКСОВАНА фаза (контроль = без трекінгу)
qs0 = [math.sin(ph[i]) for i in range(NCAR)]

got_syms    = []        # got: з фаза-трекінгом (+ переанкор OOK)
got_syms_st = []        # got_st: БЕЗ трекінгу (фіксована фаза) -> A/B показує користь PLL
for k in range(len(symbols)):
    chunk = rec[data_start + k*n : data_start + (k+1)*n]
    if len(chunk) < n:
        chunk = np.pad(chunk, (0, n - len(chunk)))
    vals = []; vals_st = []
    for i in range(NCAR):
        if is_phase[i]:                          # M-PSK
            I = float(np.dot(chunk, sin_ref[i])); Q = float(np.dot(chunk, cos_ref[i]))
            M = Mord[i]; step = two_pi / M
            # --- з трекінгом ---
            beta = math.atan2(Q * qc[i] - I * qs[i], I * qc[i] + Q * qs[i])
            sector = int(round(beta / step)) % M
            vals.append(_igray(sector))
            # слю φ_i на залишок (beta - ідеальна фаза вирішеного сектора)
            resid = beta - sector * step
            resid = (resid + math.pi) % two_pi - math.pi
            phi[i] += PLL_GAIN * resid
            qc[i] = math.cos(phi[i]); qs[i] = math.sin(phi[i])
            # --- без трекінгу (контроль) ---
            beta0 = math.atan2(Q * qc0[i] - I * qs0[i], I * qc0[i] + Q * qs0[i])
            vals_st.append(_igray(int(round(beta0 / step)) % M))
        else:                                    # OOK: 1 поріг (фаза не критична)
            d = float(np.dot(chunk, aref[i]))
            vals.append(1 if d > thr_re[i] else 0)
            vals_st.append(1 if d > thr[i] else 0)
    got_syms.append(vals); got_syms_st.append(vals_st)
got = deinterleave(syms_to_bytes_pam(got_syms, len(tx_ilv)), len(tx))
got_st = deinterleave(syms_to_bytes_pam(got_syms_st, len(tx_ilv)), len(tx))

# ---------- 7. ДІАГНОСТИКА + ВИПРАВИТИ + ЗБЕРЕГТИ ----------
raw_err    = sum(1 for a, b in zip(tx, got) if a != b)
raw_err_st = sum(1 for a, b in zip(tx, got_st) if a != b)
out(f"СИРИХ помилок: ТРЕКІНГ {raw_err}  vs  без-трекінгу {raw_err_st}  (різниця = користь PLL фаза-трекінгу)")
# помилки по ЧВЕРТЯХ передачі: рівно = одноразова калібровка тримає; росте під кінець = дрейф у часі.
_nsym = max(len(symbols), 1)
_q = [0, 0, 0, 0]
for _k, (_sent, _rcv) in enumerate(zip(symbols, got_syms)):
    _q[min(3, _k * 4 // _nsym)] += sum(1 for i in range(NCAR) if _sent[i] != _rcv[i])
out(f"помилки по чвертях часу: {_q}  (рівно=калібровка тримає; росте=дрейф у часі)")
sym_err = [0] * NCAR
for sent, rcv in zip(symbols, got_syms):
    for i in range(NCAR):
        if sent[i] != rcv[i]:
            sym_err[i] += 1
bad = {freqs[i]: sym_err[i] for i in range(NCAR) if sym_err[i]}
# чи ПЛАТИТЬ фаза: символьна помилка на фазових нотах vs OOK
nsym = max(len(symbols), 1)
nph = nq + n8
phe = sum(sym_err[i] for i in range(NCAR) if is_phase[i])
oe  = sum(sym_err[i] for i in range(NCAR) if not is_phase[i])
out(f"символьна помилка: PSK {phe}/{nph*nsym} ({100*phe/max(nph*nsym,1):.1f}%) | "
    f"OOK {oe}/{(NCAR-nph)*nsym} ({100*oe/max((NCAR-nph)*nsym,1):.1f}%)" + ("  ⚠️ PSK дорожчий за OOK" if nph and phe/max(nph*nsym,1) > 2*oe/max((NCAR-nph)*nsym,1) else "  ✓ PSK тримає"))
out("несуча | помилок | мод | калібр")
for i in range(NCAR):
    if sym_err[i]:
        _m = '8PSK' if Mord[i] == 8 else 'QPSK' if Mord[i] == 4 else 'OOK '
        out(f"  {freqs[i]:5d} | {sym_err[i]:5d} | {_m} | {ref_level[i]:.0f}")
try:
    recovered = bytes(rsc.decode(bytes(got))[0])
    open(OUT_PATH, "wb").write(recovered)
    status = "✅ ІДЕНТИЧНИЙ" if recovered == data else "⚠️ не збігся"
except Exception:
    status = "❌ RS не витягнув"
out(f"сирих: {raw_err} | {bad or 'чисто'} | {status}")

with open(RESULT_TXT, "w", encoding="utf-8") as fh:
    fh.write("\n".join(_lines) + "\n")
