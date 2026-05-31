"""
offline_decode.py — повний v0.7-декод проти реального запису (dump.npz), зі СВІПОМ таймінгу.
Реконструює active+balloc з train+sil, декодує data_tx (істина) і data_rx на зсувах вікна -12..+12.
Якщо помилка різко падає на якомусь зсуві != 0 -> баг СИНКУ (вирівнювання), фікситься.
Якщо помилка плоска по зсувах -> не таймінг (інтермод/шум) -> ARQ.
Версія: 0.001
"""
import os, math
import numpy as np

d = np.load(os.path.join(os.path.dirname(os.path.abspath(__file__)), "матеріали", "io", "dump.npz"))
sil = d["sil"].astype(float); train = d["train_rx"].astype(float)
tx = d["data_tx"].astype(float); rx = d["data_rx"].astype(float)
SR = int(d["SR"]); BIT = float(d["BIT"]); NTRAIN = int(d["NTRAIN"])
FULL = [int(x) for x in d["full_freqs"]]; PRE_F = float(d["PRE_F"]); PRE_DUR = float(d["PRE_DUR"])
NC = len(FULL); n = int(SR*BIT)
t_b = np.linspace(0, BIT, n, endpoint=False)
preamble = np.sin(2*np.pi*PRE_F*np.linspace(0, PRE_DUR, int(SR*PRE_DUR), endpoint=False))
SIN = [np.sin(2*np.pi*f*t_b) for f in FULL]; COS = [np.cos(2*np.pi*f*t_b) for f in FULL]

def sync(rec):
    return int(np.argmax(np.correlate(rec, preamble, mode="valid"))) + len(preamble)

# ---- тиша/тренування -> гейти (як offline_sweep / v0.7) ----
Wn = max(1, len(sil)//n)
noise = [float(np.mean([np.hypot(np.dot(sil[w*n:(w+1)*n], SIN[i]), np.dot(sil[w*n:(w+1)*n], COS[i])) for w in range(Wn)])) for i in range(NC)]
nmed = float(np.median(noise))
pB = sync(train)
phB = [math.atan2(np.dot(train[pB+i*n:pB+(i+1)*n], COS[i]), np.dot(train[pB+i*n:pB+(i+1)*n], SIN[i])) for i in range(NC)]
arefB = [np.cos(phB[i])*SIN[i] + np.sin(phB[i])*COS[i] for i in range(NC)]
dsB = pB + NC*n
rng = np.random.default_rng(12345)
tb = (rng.random((NTRAIN, NC)) > 0.5).astype(int)
on_s=np.zeros(NC); on_c=np.zeros(NC); off_s=np.zeros(NC); off_c=np.zeros(NC)
for k in range(NTRAIN):
    ch = train[dsB+k*n:dsB+(k+1)*n]
    if len(ch)<n: ch=np.pad(ch,(0,n-len(ch)))
    for i in range(NC):
        m=abs(float(np.dot(ch,arefB[i])))
        if tb[k,i]: on_s[i]+=m; on_c[i]+=1
        else: off_s[i]+=m; off_c[i]+=1
sep=[(on_s[i]/max(on_c[i],1))/max(off_s[i]/max(off_c[i],1),1e-9) for i in range(NC)]
on_tr=[on_s[i]/max(on_c[i],1) for i in range(NC)]; off_tr=[off_s[i]/max(off_c[i],1) for i in range(NC)]
thr_all=[math.sqrt(max(on_tr[i],1e-9)*max(off_tr[i],1e-9)) for i in range(NC)]
nerr=np.zeros(NC)
for k in range(NTRAIN):
    ch=train[dsB+k*n:dsB+(k+1)*n]
    if len(ch)<n: ch=np.pad(ch,(0,n-len(ch)))
    for i in range(NC):
        if (1 if float(np.dot(ch,arefB[i]))>thr_all[i] else 0)!=int(tb[k,i]): nerr[i]+=1
err=[nerr[i]/NTRAIN for i in range(NC)]

# гейти v0.7
def _q(x): return 0.5*math.erfc(x/math.sqrt(2))
def psk_serr(s,M): return 2*_q(s*0.7*math.sin(math.pi/M))
active=[i for i in range(NC) if sep[i]>=1.5 and noise[i]<=8*nmed and err[i]<=0.03]
NA=len(active)
# balloc / Mord на active
balloc=[]; Mord=[]
for i in active:
    if err[i]==0 and psk_serr(sep[i],8)<0.01: balloc.append(3); Mord.append(8)
    elif err[i]==0 and psk_serr(sep[i],4)<0.01: balloc.append(2); Mord.append(4)
    else: balloc.append(1); Mord.append(0)
# active-простір референси/пороги (як rebuild у loopback)
aSIN=[SIN[i] for i in active]; aCOS=[COS[i] for i in active]
a_on=[on_tr[i] for i in active]; a_off=[off_tr[i] for i in active]
a_thr=[math.sqrt(max(a_on[j],1e-9)*max(a_off[j],1e-9)) for j in range(NA)]
print(f"active {NA} нот | 8PSK {Mord.count(8)} QPSK {Mord.count(4)} OOK {balloc.count(1)} | nmed={nmed:.3f}")

def gray(v): return v^(v>>1)
def igray(g):
    m=g>>1
    while m: g^=m; m>>=1
    return g

def decode(rec, off, pll=0.0):
    """декод rec зі зсувом off; pll>0 -> фаза-трекінг із цим gain. Повертає вектори значень."""
    p = sync(rec)
    ph=[math.atan2(np.dot(rec[p+j*n:p+(j+1)*n], aCOS[j]), np.dot(rec[p+j*n:p+(j+1)*n], aSIN[j])) for j in range(NA)]
    qc=[math.cos(x) for x in ph]; qs=[math.sin(x) for x in ph]
    aref=[np.cos(ph[j])*aSIN[j]+np.sin(ph[j])*aCOS[j] for j in range(NA)]
    phi=list(ph)
    ds = p + NA*n + off
    nsym = (len(rec)-ds)//n
    syms=[]
    for k in range(nsym):
        seg=rec[ds+k*n:ds+(k+1)*n]
        if len(seg)<n: seg=np.pad(seg,(0,n-len(seg)))
        v=[]
        for j in range(NA):
            if Mord[j]:
                I=float(np.dot(seg,aSIN[j])); Q=float(np.dot(seg,aCOS[j])); M=Mord[j]; stp=2*math.pi/M
                beta=math.atan2(Q*qc[j]-I*qs[j], I*qc[j]+Q*qs[j])
                sec=int(round(beta/stp))%M; v.append(igray(sec))
                if pll:
                    r=beta-sec*stp; r=(r+math.pi)%(2*math.pi)-math.pi
                    phi[j]+=pll*r; qc[j]=math.cos(phi[j]); qs[j]=math.sin(phi[j])
            else:
                v.append(1 if float(np.dot(seg,aref[j]))>a_thr[j] else 0)
        syms.append(v)
    return syms

# істина з data_tx (чистий канал)
truth = decode(tx, 0)
nsym = len(truth)
print(f"символів даних: {nsym}")

print("\nСВІП ТАЙМІНГУ декоду data_rx (зсув вікна -> % символьних помилок):")
best=(0,1e9)
for off in range(-12,13,2):
    got=decode(rx, off)
    L=min(len(got),nsym)
    e=sum(1 for k in range(L) for j in range(NA) if got[k][j]!=truth[k][j])
    tot=L*NA; pct=100*e/max(tot,1)
    bar='#'*int(pct)
    print(f"  off {off:+3d}: {pct:5.1f}%  {bar}")
    if pct<best[1]: best=(off,pct)
print(f"\nмінімум: off {best[0]:+d} -> {best[1]:.1f}%  (мінімум на 0 = синк правильний, не таймінг)")

# ---- ДЕ живе помилка: по режимах (off=0) ----
def mode_breakdown(pll):
    got=decode(rx,0,pll=pll); L=min(len(got),nsym)
    em={1:[0,0],4:[0,0],8:[0,0]}  # [errors, total]
    for k in range(L):
        for j in range(NA):
            M = Mord[j] if Mord[j] else 1
            em[M][1]+=1
            if got[k][j]!=truth[k][j]: em[M][0]+=1
    return em
print("\nПОМИЛКА ПО РЕЖИМАХ (off=0):")
for pll,lbl in [(0.0,"без PLL"),(0.08,"PLL 0.08 (v0.7)"),(0.2,"PLL 0.2"),(0.4,"PLL 0.4")]:
    em=mode_breakdown(pll)
    s=" | ".join(f"{ {1:'OOK',4:'QPSK',8:'8PSK'}[M] } {100*em[M][0]/max(em[M][1],1):4.1f}%" for M in (1,4,8))
    tot=sum(em[M][0] for M in em); alltot=sum(em[M][1] for M in em)
    print(f"  {lbl:16s}: {s}  | разом {100*tot/max(alltot,1):.1f}%")
# ---- ПЕРЕАНКОР: дрейф рівня train->data, тест ширини клампа на OOK-помилці ----
pR = sync(rx)
calB = [math.hypot(np.dot(train[pB+active[j]*n:pB+(active[j]+1)*n], SIN[active[j]]),
                   np.dot(train[pB+active[j]*n:pB+(active[j]+1)*n], COS[active[j]])) for j in range(NA)]
refL = [math.hypot(np.dot(rx[pR+j*n:pR+(j+1)*n], aSIN[j]), np.dot(rx[pR+j*n:pR+(j+1)*n], aCOS[j])) for j in range(NA)]
driftj = [refL[j]/max(calB[j],1e-9) for j in range(NA)]
ook_idx = [j for j in range(NA) if Mord[j]==0]
print(f"\nдрейф рівня train->data: медіана {np.median(driftj):.2f}, діапазон {min(driftj):.2f}..{max(driftj):.2f}")
print("OOK-помилка при різних клампах переанкору (off=0):")
truth0 = truth
for lo,hi,lbl in [(1.0,1.0,"БЕЗ переанкору"),(0.6,1.7,"кламп [0.6,1.7] (v0.7)"),(0.4,2.5,"кламп [0.4,2.5]"),(0.2,5.0,"кламп [0.2,5.0]"),(0.0,99,"повний (без клампу)")]:
    p=sync(rx); ds=p+NA*n
    e=0; tot=0
    for k in range(min(nsym,(len(rx)-ds)//n)):
        seg=rx[ds+k*n:ds+(k+1)*n]
        if len(seg)<n: seg=np.pad(seg,(0,n-len(seg)))
        for j in ook_idx:
            dr=min(hi,max(lo,driftj[j]))
            bit=1 if float(np.dot(seg,np.cos(math.atan2(np.dot(rx[p+j*n:p+(j+1)*n],aCOS[j]),np.dot(rx[p+j*n:p+(j+1)*n],aSIN[j])))*aSIN[j]+np.sin(math.atan2(np.dot(rx[p+j*n:p+(j+1)*n],aCOS[j]),np.dot(rx[p+j*n:p+(j+1)*n],aSIN[j])))*aCOS[j]))>a_thr[j]*dr else 0
            tot+=1
            if bit!=truth0[k][j]: e+=1
    print(f"  {lbl:22s}: OOK {100*e/max(tot,1):.1f}%")
print("\nякщо ширший кламп різко роняє OOK -> великий дрейф рівня, фікс = ширший/розумніший переанкор.")
