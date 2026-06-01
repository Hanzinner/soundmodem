// Reed-Solomon over GF(256), primitive poly 0x11d (same as Python reedsolo defaults).
// Systematic encode + full decode (syndromes, Berlekamp-Massey, Chien, Forney).
// Self-contained; the functions below get inlined into index.html. Node-testable.
"use strict";

const GF_EXP = new Uint8Array(512);
const GF_LOG = new Uint8Array(256);
(function initGF(){
  let x = 1;
  for (let i = 0; i < 255; i++){
    GF_EXP[i] = x;
    GF_LOG[x] = i;
    x <<= 1;
    if (x & 0x100) x ^= 0x11d;
  }
  for (let i = 255; i < 512; i++) GF_EXP[i] = GF_EXP[i - 255];
})();

function gfMul(a, b){ if (a === 0 || b === 0) return 0; return GF_EXP[GF_LOG[a] + GF_LOG[b]]; }
function gfPow(a, n){ const e = ((GF_LOG[a] * n) % 255 + 255) % 255; return GF_EXP[e]; }
function gfInv(a){ return GF_EXP[255 - GF_LOG[a]]; }
function gfDiv(a, b){ if (a === 0) return 0; return GF_EXP[(GF_LOG[a] + 255 - GF_LOG[b]) % 255]; }

// ---- polynomial helpers on plain Arrays (right-aligned, MSB-first) ----
function pScale(p, x){ return p.map(c => gfMul(c, x)); }
function pAdd(p, q){
  const r = new Array(Math.max(p.length, q.length)).fill(0);
  for (let i = 0; i < p.length; i++) r[i + r.length - p.length] = p[i];
  for (let i = 0; i < q.length; i++) r[i + r.length - q.length] ^= q[i];
  return r;
}
function pMul(p, q){
  const r = new Array(p.length + q.length - 1).fill(0);
  for (let i = 0; i < p.length; i++)
    for (let j = 0; j < q.length; j++)
      r[i + j] ^= gfMul(p[i], q[j]);
  return r;
}
function pEval(p, x){ let y = p[0]; for (let i = 1; i < p.length; i++) y = gfMul(y, x) ^ p[i]; return y; }

function polyMul(p, q){
  const r = new Uint8Array(p.length + q.length - 1);
  for (let i = 0; i < p.length; i++)
    for (let j = 0; j < q.length; j++)
      r[i + j] ^= gfMul(p[i], q[j]);
  return r;
}
function polyEval(p, x){
  let y = p[0];
  for (let i = 1; i < p.length; i++) y = gfMul(y, x) ^ p[i];
  return y;
}

function rsGenerator(nsym){
  let g = new Uint8Array([1]);
  for (let i = 0; i < nsym; i++) g = polyMul(g, new Uint8Array([1, gfPow(2, i)]));
  return g;
}

// msg = Uint8Array of length K; returns Uint8Array length K+nsym (systematic)
function rsEncode(msg, nsym){
  const gen = rsGenerator(nsym);
  const out = new Uint8Array(msg.length + nsym);
  out.set(msg, 0);
  for (let i = 0; i < msg.length; i++){
    const coef = out[i];
    if (coef !== 0)
      for (let j = 1; j < gen.length; j++)
        out[i + j] ^= gfMul(gen[j], coef);
  }
  out.set(msg, 0); // restore systematic prefix (the loop above clobbered only parity tail positions >= K)
  return out;
}

function rsSyndromes(msg, nsym){
  const s = new Uint8Array(nsym);
  for (let i = 0; i < nsym; i++) s[i] = polyEval(msg, gfPow(2, i));
  return s;
}

function rsErrorLocator(synd){
  let errLoc = [1], oldLoc = [1];
  for (let i = 0; i < synd.length; i++){
    let delta = synd[i];
    for (let j = 1; j < errLoc.length; j++)
      delta ^= gfMul(errLoc[errLoc.length - 1 - j], synd[i - j]);
    oldLoc = oldLoc.concat([0]);
    if (delta !== 0){
      if (oldLoc.length > errLoc.length){
        const newLoc = pScale(oldLoc, delta);
        oldLoc = pScale(errLoc, gfInv(delta));
        errLoc = newLoc;
      }
      errLoc = pAdd(errLoc, pScale(oldLoc, delta));
    }
  }
  while (errLoc.length && errLoc[0] === 0) errLoc.shift();
  return errLoc;
}

function rsErrorPositions(errLoc, nmess){
  // Chien search: Λ(α^i)=0 → coef_pos=(255-i) mod 255, byte index = (nmess-1)-coef_pos.
  const errs = errLoc.length - 1;
  const pos = [];
  for (let i = 0; i < 255; i++){
    if (pEval(errLoc, gfPow(2, i)) === 0){
      const coefPos = (255 - i) % 255;
      const bi = (nmess - 1) - coefPos;
      if (bi >= 0 && bi < nmess) pos.push(bi);
    }
  }
  return pos.length === errs ? pos : null;
}

function rsCorrect(msg, synd, errPos){
  const coefPos = errPos.map(p => msg.length - 1 - p);
  // errata locator from positions
  let eLoc = [1];
  for (const p of coefPos) eLoc = pMul(eLoc, pAdd([1], [gfPow(2, p), 0]));
  // error evaluator = (synd_rev * eLoc) mod x^(len) -> keep last (len) coeffs
  const syndRev = Array.from(synd).reverse();
  let evaluator = pMul(syndRev, eLoc);
  evaluator = evaluator.slice(evaluator.length - eLoc.length);   // remainder mod x^(eLoc.length)
  // Forney
  const X = coefPos.map(p => gfPow(2, p));
  const out = Uint8Array.from(msg);
  for (let i = 0; i < X.length; i++){
    const XiInv = gfInv(X[i]);
    let denom = 1;
    for (let j = 0; j < X.length; j++){
      if (j !== i) denom = gfMul(denom, 1 ^ gfMul(XiInv, X[j]));
    }
    if (denom === 0) return null;
    // Forney: Λ'(X⁻¹)=Xᵢ·denom, the Xᵢ factor cancels → magnitude = Ω(X⁻¹)/denom (no extra Xᵢ).
    const y = pEval(evaluator, XiInv);
    out[errPos[i]] ^= gfDiv(y, denom);
  }
  return out;
}

// returns {ok:bool, msg:Uint8Array(K)} ; nsym = parity length, K = block.length - nsym
function rsDecode(block, nsym){
  const msg = Uint8Array.from(block);
  const synd = rsSyndromes(msg, nsym);
  let zero = true;
  for (const s of synd) if (s !== 0){ zero = false; break; }
  if (zero) return { ok: true, msg: msg.slice(0, block.length - nsym) };
  const errLoc = rsErrorLocator(synd);
  const pos = rsErrorPositions(errLoc, msg.length);
  if (!pos) return { ok: false, msg: null };
  if (pos.length > nsym / 2) return { ok: false, msg: null };
  const corrected = rsCorrect(msg, synd, pos);
  if (!corrected) return { ok: false, msg: null };
  // verify
  const synd2 = rsSyndromes(corrected, nsym);
  for (const s of synd2) if (s !== 0) return { ok: false, msg: null };
  return { ok: true, msg: corrected.slice(0, block.length - nsym) };
}

if (typeof module !== "undefined") module.exports = { rsEncode, rsDecode, GF_EXP, GF_LOG };
