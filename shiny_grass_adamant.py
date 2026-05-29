"""Thorough offline+verify hunt for the best Adamant shiny Mankey.

Mandatory: Adamant nature, Attack=31, Speed=31. Then maximise perfect IVs with
priority HP > Def (SpA/SpD are throwaway for a physical attacker).

IVs here are INDEPENDENT of shininess (separate RNG calls after the nature-lock
loop), so high-IV counts are reachable (no starter-style coupling cap). Speed
(iv2) has the VBlank-gap ambiguity, so the offline IV prediction is a prior;
truth comes from emulator verification. Enumerate full 2^32 gen-seeds, pre-
filtering to Mankey-slot + Adamant BEFORE the loop (≈80x less loop work), then
verify the most promising candidates.
"""
import time, sys, json, numpy as np
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file, save_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted
from pokemon_agent.gen3_rng import rewind, generate_wild

ROM="roms/Pokemon - LeafGreen Version (USA).gba"; STATE="roms/Pokemon - LeafGreen Version (USA).ss2"
ENEMY=0x0202402C; RNG=0x03005000; TID,SID=51376,36462
MANKEY_SLOTS=(1,3); ADAMANT=3; OFFSETS=(294,276,258)
BEST_LOG="adamant_best.jsonl"
A=np.uint64(0x41C64E6D); C=np.uint64(0x6073); M=np.uint64(0xFFFFFFFF)
def step(s): return (s*A+C)&M
def ivword(v): return (int(v)&31,(int(v)>>5)&31,(int(v)>>10)&31)

def enumerate_candidates(total=1<<32, chunk=1<<22):
    """Return list of (G, pid) for shiny + Mankey-slot + Adamant gen-seeds."""
    xb=np.uint64((TID^SID)&0xFFFF); cums=np.cumsum([20,20,10,10,10,10,5,5,4,4,1,1])
    out=[]; base=0; t0=time.time()
    while base<total:
        G=np.arange(base, base+chunk, dtype=np.uint64); base+=chunk
        s=step(G); slot=np.searchsorted(cums,(s>>np.uint64(16))%np.uint64(100),side='right')
        s=step(s)                                   # level
        s=step(s); nat=((s>>np.uint64(16))%np.uint64(25))
        keep=((slot==1)|(slot==3))&(nat==ADAMANT)   # PRE-LOOP filter (cheap)
        gi=np.nonzero(keep)[0]
        if gi.size:
            Gs=G[gi]; cur=s[gi].copy(); matched=np.zeros(gi.size,bool); pid=np.zeros(gi.size,np.uint64)
            for _ in range(200):
                s1=step(cur); lo=s1>>np.uint64(16); s2=step(s1); hi=s2>>np.uint64(16)
                p=((hi<<np.uint64(16))|lo)&M
                nm=(~matched)&((p%np.uint64(25))==ADAMANT)
                pid[nm]=p[nm]; matched|=nm; cur=s2
                if matched.all(): break
            pl=pid&np.uint64(0xFFFF); ph=pid>>np.uint64(16)
            sh=matched&(((xb^ph^pl)&np.uint64(0xFFFF))<np.uint64(8))
            for e in np.nonzero(sh)[0]:
                out.append((int(Gs[e]), int(pid[e])))
        if base % (1<<28)==0:
            print("  enum %d/%d (%.0f%%) cand=%d %.0fs"%(base,total,100*base/total,len(out),time.time()-t0)); sys.stdout.flush()
    return out

def main():
    mgba.log.silence()
    core=mgba.core.load_path(ROM); fb=mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb); core.reset(); load_state_file(core,STATE)
    base=bytes(core.save_raw_state()); mem=core.memory; L,R=core.KEY_LEFT,core.KEY_RIGHT
    def emulate(V):
        core.load_raw_state(base); mem.u32[RNG]=V; bp=mem.u32[ENEMY]; i=0
        while i<70:
            btn=L if i%2==0 else R
            for ph in range(3):
                core.set_keys(btn) if ph<2 else core.set_keys(); core.run_frame()
                if mem.u32[ENEMY]!=bp: i=999;break
            if i==999:break
            i+=1
        for _ in range(20): core.run_frame()
        mon=b"".join(mem.u32[ENEMY+4*k].to_bytes(4,"little") for k in range(25))
        pid=int.from_bytes(mon[0:4],"little"); otid=int.from_bytes(mon[4:8],"little")
        dec=decrypt_block(mon[0x20:0x20+48],pid,otid)
        return int.from_bytes(dec[0:2],"little"),pid,ivs_from_decrypted(dec).as_tuple()
    def n31(iv): return sum(1 for x in iv if x==31)
    def score(iv):  # rank: Atk31&Spe31 mandatory, then #31, then HP, then Def
        ok=(iv[1]==31 and iv[3]==31)
        return (ok, n31(iv), iv[0], iv[2], sum(iv))

    print("enumerating shiny+Mankey+Adamant gen-seeds over full 2^32...")
    t0=time.time(); cands=enumerate_candidates()
    print("offline done: %d Adamant candidates in %.0fs"%(len(cands),time.time()-t0))
    # verify all; for each G try offsets until emulated pid==G's pid -> true IVs
    best=None; checked=0; t1=time.time(); a31s31=[]
    for G,P in cands:
        for off in OFFSETS:
            sp,pid,iv=emulate(rewind(G,off)); checked+=1
            if pid==P and sp==56:
                if iv[1]==31 and iv[3]==31: a31s31.append((G,off,pid,iv))
                if best is None or score(iv)>score(best[3]):
                    best=(G,off,pid,iv)
                    open(BEST_LOG,"a").write(json.dumps({"ts":time.time(),"write":"0x%08X"%rewind(G,off),"ivs":list(iv),"n31":n31(iv)})+"\n")
                    print("  new best: write=0x%08X IVs%s #31=%d (Atk31&Spe31=%s)"%(rewind(G,off),iv,n31(iv),iv[1]==31 and iv[3]==31)); sys.stdout.flush()
                break
    print("verify done: checked %d emulations in %.0fs; Atk31&Spe31 found: %d"%(checked,time.time()-t1,len(a31s31)))
    if best:
        G,off,pid,iv=best
        emulate(rewind(G,off)); save_state_file(core,"roms/leafgreen_shiny_mankey_adamant.ss1")
        print("BEST Adamant: write=0x%08X IVs(H,A,D,Sp,SpA,SpD)=%s #31=%d -> roms/leafgreen_shiny_mankey_adamant.ss1"%(rewind(G,off),iv,n31(iv)))

if __name__=="__main__": main()
