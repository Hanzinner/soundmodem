# Web modem (browser, for phones)

The browser port runs as a static page on GitHub Pages — no install, works on a phone.
It is a **port of the desktop architecture**, not a separate invention, but it deliberately
diverges where the physics differ (see "Why it's not the desktop code" below).

Two files:
- **`index.html`** — production page (older v0.5: OOK + CRC-32, no error correction). Stable.
- **`dev.html`** — testing page with the full stack: Reed-Solomon error correction, block
  framing, and block accumulation across replays. Tested in Node, not yet field-proven on two
  phones — that's what it's for.
- **`rs.js`** — the Reed-Solomon codec as a standalone, Node-testable module. `dev.html` inlines
  the same code; `rs.js` exists so the correction math can be unit-tested outside a browser.

## How the web modem works

Same OFDM-OOK core as desktop, simplified for the browser and the two-device reality:

1. **14 carriers**, 1000–3600 Hz, 200 Hz spacing. A narrow, safe band where phone speakers and
   microphones are both clean. (Desktop uses ~150 carriers across 520 Hz–20 kHz; phones don't
   have that clean range.)
2. **OOK only** (tone on = 1, off = 0). No phase modulation — see below.
3. **Chirp preamble** (1200→3800 Hz sweep) per block, for a sharp matched-filter sync.
4. **Per-block calibration**: an all-carriers-on symbol right after each chirp measures each
   carrier's phase and level *for that block*, so the decision threshold re-anchors locally.
5. **Coherent detection with local-index projection.** The receiver projects each symbol using a
   per-symbol local sample index (0..n), exactly matching how the transmitter builds each symbol
   (phase resets every symbol). Using the absolute sample index instead breaks when `n =
   round(sr*BIT)` rounding makes `freq*n/sr` non-integer — phase then drifts across symbols and
   the block dies. (This was a real bug found during Node validation.)

## Error correction & framing

- The file is wrapped as `payload = u32(len) + u32(crc32) + fileBytes`.
- `payload` is split into chunks of `DATA = (255 - parity) - 4` bytes.
- Each chunk becomes a 255-byte **Reed-Solomon block**: `[u16 idx][u16 total][chunk]` then
  RS-encoded. RS corrects up to `parity/2` corrupted bytes per block.
- Each block is transmitted independently (own chirp + calib), so blocks survive on their own.

## ARQ via replays (no back-channel)

Two phones have no automatic back-channel, so ARQ works by **accumulation**:

- The receiver scans a recording for **all** chirps, decodes every block it can, and stores each
  recovered block by its index in a map that **persists across decodes**.
- The progress bar shows `X / N` blocks captured.
- If not all blocks arrived, the user just **plays the same file again**; the receiver fills in
  the still-missing blocks. The human watching `48/58` is the back-channel.
- When all `N` blocks are present, the file is reassembled and the CRC verified.

`↺ СКИНУТИ` clears the accumulation to start a new file.

## Modes (the buttons)

| Mode | BIT (symbol time) | RS parity | corrects/block |
|---|---|---|---|
| ⚡ ШВИДКО (fast) | 0.035 s | 32 | up to 16 bytes |
| 🛡 НАДІЙНО (safe) | 0.050 s | 64 | up to 32 bytes |

Default is **safe** — two real devices over air is a dirty channel.

## 🧪 Self-test

The `САМОТЕСТ` button synthesizes a signal in memory, adds noise + clipping, and decodes it —
no microphone needed. It proves the RS + framing + sync + accumulate chain end-to-end in the
page itself. (The same pipeline is also validated in Node against the real `rs.js`.)

## Why it's not the desktop Python code

You can't run the Python in a browser — no `numpy`, no `sounddevice`, no `reedsolo` (a compiled
C library). The page is pure HTML+JS. So the architecture is ported; the code is new because the
language and the runtime are different. Three divergences are forced by physics, not translation:

1. **OOK instead of QPSK/8-PSK.** Desktop's main speed trick — phase modulation — relies on the
   transmitter and receiver sharing **one crystal clock** (it's one laptop). Two phones have
   **different crystals**: a constant frequency offset rotates the phase, which destroys PSK.
   OOK (amplitude) survives different crystals, so the web port stays on OOK.
2. **14 carriers, not ~150.** Phone speaker+mic are only clean over a narrow mid band.
3. **ARQ by replay, not one-machine.** Desktop loopback is one program that already knows which
   blocks failed; two phones need the human-in-the-loop replay accumulation above.

## Current state & findings (2026-06)

The dev page has iterated to **v0.10**: Reed-Solomon, block accumulation, telemetry (button
events + an audio signature: per-carrier levels, a coarse spectrum, sync strength, RS errors),
a TX progress bar, a live block grid, and a **visible per-carrier spectrum** so the channel's
alive/dead carriers are seen in-UI.

Real-hardware testing surfaced the core limit, and two offline proofs framed the fix:

- **Flat, blind OOK fails on a real narrow channel.** On a laptop loopback the recorded signal
  was weak (peak ~0.04) and only the ~900–1300 Hz carriers were alive; the rest sat at noise.
  Chirp sync found every block, but 0 decoded — the dead carriers still occupy bit-slots and
  poison every byte beyond RS's reach (~32% bit-error, reproduced offline against the real
  per-carrier signature).
- **Receiver-side gain/EQ alone can't fix it.** Dropping dead carriers at the receiver doesn't
  help, because the transmitter already committed data to them. The fix requires the
  **transmitter to know the channel** — which means a **probe round**.
- **The high band is where the bandwidth is.** The desktop modem gets its throughput from
  8–20 kHz with per-carrier pre-emphasis and gating. The web port currently neither uses that
  band nor pre-emphasises, so high carriers roll off and die. Same hardware, different result —
  it's adaptation, not physics.
- **Two crystals are correctable.** Offline, a 180 ppm sample-rate offset between two devices was
  estimated to 0.1 ppm from a pilot and resampled out, leaving 0.3° of residual phase drift over
  a whole transfer — enough to make phase modulation (QPSK) viable across two devices.

## Roadmap (web)
The next build is a **probe round** (a short handshake), which unlocks several things at once:
- Measure the channel per carrier, **gate** dead carriers, **pre-emphasise** weak-but-live ones.
- **Extend into the 8–20 kHz band** and keep whatever the probe confirms (per-device, since some
  phone browsers resample mic input down to ~16 kHz).
- On two devices, the same handshake carries **sample-clock (ppm) correction** → phase modulation
  → per-carrier **bit-loading**, plus a real back-channel for ARQ.
- Optional ultrasonic (~19 kHz) "silent mode" once the band is probe-driven.
