# soundmodem

A from-scratch **acoustic modem**: send a file (e.g. an image) as **sound through the air**
and receive it back **bit-for-bit identical**, with forward error correction.

The honest test setup — and the whole point — is the dirty channel:

```
file → laptop speaker → OPEN AIR of a room → same laptop's microphone → file
```

No cable. No line-in loopback. Real air, real room reverb, real cooler-fan noise,
real channel that drifts. This is much harder than the cable/line-in loopback that
most published "headline" numbers (40+ kbps) are actually measured on.

---

## Numbers (real hardware, over air)

| Metric | Value |
|---|---|
| Net throughput (after error correction) | **~5,600 bit/s** |
| Raw throughput (before correction) | ~8,800 bit/s |
| Frequency band | **520 Hz – 20 kHz** (audible, **not** ultrasonic) |
| Active carriers (per run, channel-dependent) | ~150 simultaneous tones |
| Reliability | pixel-perfect (image bytes match exactly) |

A 9 KB image transfers in ~15 seconds, byte-for-byte.

These numbers are measured **through air at normal listening volume**, not over a cable.
On an equal channel (air, audible) they are competitive with anything public; the famous
"tens of kbps" figures from other libraries are **cable** figures.

---

## How it works (architecture)

### 1. OFDM core
Instead of sending one tone at a time, ~150 tones play **simultaneously**, each one an
independent data channel (like an orchestra where every instrument carries its own bits).
Orthogonal Frequency-Division Multiplexing.

### 2. Adaptive per-carrier modulation (bit-loading)
Every carrier is **not** treated equally. Before each transfer, a training pattern measures
each tone's actual quality on **this** channel right now, and assigns it a scheme:

| Tone quality | Scheme | Bits/tone |
|---|---|---|
| clean | **8-PSK** (phase in 8 positions) | 3 |
| good | **QPSK** (phase in 4 positions) | 2 |
| weak | **OOK** (on/off keying — tone present = 1) | 1 |
| dead | dropped | 0 |

Phase modulation (PSK) is **amplitude-immune**: because transmitter and receiver share the
**same crystal clock** (it's one laptop), the phase is stable even when the loudness drifts.
This is the key trick — most of the speed comes from it. A fixed profile (what most libraries
ship) would leave this on the table; per-carrier adaptation is the edge on a non-flat channel.

### 3. Three gates select which tones to use
- **Noise gate** — 2 s of pre-flight silence measures each tone's noise floor; tones sitting
  in noise hotspots (the cooler fan is a low-frequency enemy) are dropped.
- **Error gate** (the main one) — the training pattern measures each tone's *actual* bit-error
  rate under load; tones flipping > 3 % are dropped. This single gate empirically beats the
  separation + noise gates combined.
- **Separation gate** — a rail that drops tones whose on/off contrast collapses.

### 4. Error correction — adaptive Reed-Solomon
The file is split into fixed blocks. Each block carries spare bytes (Reed-Solomon) so a
limited number of corrupted bytes can be reconstructed mathematically. The amount of spare
(parity) is **chosen per run** from the measured/predicted error rate, with a floor for the
channel's worst moments.

### 5. ARQ — automatic repeat request (the non-stationarity answer)
Forensic analysis (`offline_forensics.py`, `offline_decode.py`) proved that failed transfers
were **not** a decode/sync/timing bug — the air channel genuinely **drifts** (level moves ~2×
within seconds; "bad moments"). No decode tweak fixes that fundamentally.

The answer is ARQ: the decoder **knows which blocks failed** — a Reed-Solomon block either
decodes cleanly or throws (too many errors) — so only the **failed blocks are re-sent** on the
next pass, hopefully catching a cleaner moment. Good moment → 1 pass. Bad → 2–3.

Because transmitter and receiver are the **same program on one machine**, this is one-way:
no back-channel is needed — the sender already sees which blocks didn't decode.

**Crucial detail (`loopback_arq.py`, arq-0.2):** interleaving is done **within each block**,
not across blocks. An earlier version spread time-bursts across all blocks, so one bad moment
killed *all* of them (0/58). Per-block interleaving makes blocks **independent** — a localized
bad window kills only the blocks played during it; the rest decode and ARQ re-sends just the
casualties. Real-hardware run (full log: [`results/hardware_run_arq-0.2.txt`](results/hardware_run_arq-0.2.txt)):
pass 1 recovered 31/58, pass 2 recovered the remaining 27 → file identical, 5639 bit/s net.

---

## Files

| File | What it is |
|---|---|
| `python/loopback.py` | the main modem (adaptive M-PSK champion) |
| `python/loopback_arq.py` | modem + block ARQ (re-send failed blocks) |
| `python/arq_sim.py` | hardware-free convergence test (mocked channel) |
| `python/offline_forensics.py` | clock-drift / timing analysis on a real recording |
| `python/offline_decode.py` | full decode replay on a real recording with timing sweep |
| `index.html` | browser port (Web Audio API) for phones — GitHub Pages |

## Run (desktop)

```bash
pip install numpy sounddevice reedsolo
# put any input.* (png/jpg/avif/txt) in the io folder
python3 python/loopback_arq.py
```

It plays sound, records itself, and writes `output.*` next to the input. They should match.

> Note: put **one** `input.*` file in the io folder — newest wins.

---

## Honest comparison

- **quiet.js** (liquid-dsp + libfec): mature, ships convolutional codes + Reed-Solomon. Its
  headline ~40 kbps is **over a cable**; its over-air audible profile is much slower. Fixed
  profile, not per-carrier adaptive.
- **amodem** (Roman Zeyde): Python OFDM up to 256-QAM with carrier-tone sync, sampler PLL, FIR
  equalizer — measured on an **audio cable**.

What this project does differently: **per-carrier adaptive bit-loading on a real air channel**,
with ARQ for channel non-stationarity. That niche (over-air, audible, adaptive) is rare.

## Roadmap
- Convolutional codes + Viterbi as a second correction layer on top of Reed-Solomon
  (the one thing worth borrowing from quiet/libfec — catches scattered errors RS misses).
- FIR channel equalizer.
- Two-device mode (different crystals → needs a sample-clock recovery loop + a real back-channel for ARQ).

## License
MIT — see `LICENSE`.
