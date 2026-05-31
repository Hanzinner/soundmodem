"""
arq_sim.py — валідація ЗБІЖНОСТІ ARQ без заліза. Мок-канал: кожен playrec-прохід має ВИПАДКОВУ
якість (іноді шумний -> частина RS-блоків падає -> ARQ дослати их -> добрий прохід ловить).
Перевіряємо: loopback_arq.py збігається до ✅ ІДЕНТИЧНИЙ за кілька проходів.
запуск: python3 arq_sim.py
Версія: 0.001
"""
import os, sys, types
import numpy as np

os.environ["NODUMP"] = "1"
np.random.seed(3)
SR = 44100
_call = {"n": 0}

def _playrec(buf, sr, channels=1):
    _call["n"] += 1
    x = np.asarray(buf).reshape(-1).astype(float)
    # прохід 1 = калібр-зонд (чистий), далі дата-проходи з ВИПАДКОВИМ шумом
    # _call 1-2 = зонд/тренування (чисто); далі дата-проходи з НАРОСТАЮЧОЮ чистотою
    # (перший дата-прохід шумний -> частина блоків падає -> ретрай -> чистіші проходи ловлять)
    sched = {1: 0.0008, 2: 0.0008, 3: 0.055, 4: 0.02, 5: 0.006, 6: 0.003}
    noise = sched.get(_call["n"], 0.003)
    y = x + 0.12 * np.sign(x) * x * x + np.random.normal(0, noise, len(x))
    return y.reshape(-1, 1)

def _rec(frames, samplerate=44100, channels=1):
    return np.random.normal(0, 0.0008, frames).reshape(-1, 1)

fake = types.ModuleType("sounddevice")
fake.playrec = _playrec; fake.rec = _rec; fake.wait = lambda: None
sys.modules["sounddevice"] = fake

print("[arq_sim] мок-канал з випадковою якістю проходів -> перевіряю збіжність ARQ\n")
HERE = os.path.dirname(os.path.abspath(__file__))
src = open(os.path.join(HERE, "loopback_arq.py"), encoding="utf-8").read()
exec(compile(src, "loopback_arq.py", "exec"), {"__name__": "__main__", "__file__": os.path.join(HERE, "loopback_arq.py")})
