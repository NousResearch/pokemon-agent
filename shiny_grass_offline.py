"""Offline-accelerated shiny wild hunt (hybrid) for LeafGreen.

Uses the decoded RNG (pokemon_agent/gen3_rng.py): the encounter is a pure
function of the written gRngValue seed. PID/nature/species are 100% predictable
offline; only the IVs' 2nd word has a VBlank-gap ambiguity. So we:

  1. OFFLINE (numpy): enumerate generation seeds G, keep shiny + Mankey + a
     physical-usable nature, ranked by predicted Attack (reliable) + Speed.
  2. VERIFY (emulator): for each candidate write rewind(G, 294) into gRngValue,
     jiggle to the encounter, read the ACTUAL mon (true IVs), keep the best.

Far faster than the blind search for a *specific nature* + good Attack, because
shininess is computed, not stumbled upon.
"""
import time, numpy as np
import mgba.core, mgba.image, mgba.log
from pokemon_agent.gba_state import load_state_file
from pokemon_agent.shiny_gen3 import lcg_next, decrypt_block, ivs_from_decrypted
from pokemon_agent.gen3_rng import rewind, SLOT_CUMULATIVE, generate_wild

ROM="roms/Pokemon - LeafGreen Version (USA).gba"; STATE="roms/Pokemon - LeafGreen Version (USA).ss2"
ENEMY=0x0202402C; RNG=0x03005000; TID,SID=51376,36462
MANKEY_SLOTS=(1,3); GEN_OFFSET=294
NAT=["Hardy","Lonely","Brave","Adamant","Naughty","Bold","Docile","Relaxed","Impish","Lax","Timid","Hasty","Serious","Jolly","Naive","Modest","Mild","Quiet","Bashful","Rash","Calm","Gentle","Sassy","Careful","Quirky"]
def phys_ok(n): inc,dec=n//5,n%5; return not((dec==0 and inc!=0) or (dec==2 and inc!=2))
PHYS=np.array([phys_ok(n) for n in range(25)])  # physical-usable natures (default)
A=np.uint64(0x41C64E6D); C=np.uint64(0x6073); M=np.uint64(0xFFFFFFFF)
def step(s): return (s*A+C)&M

def offline_candidates(n_seeds=60_000_000, chunk=1<<21, maxloop=160):
    xb=np.uint64((TID^SID)&0xFFFF)
    cums=np.cumsum([20,20,10,10,10,10,5,5,4,4,1,1])  # slot thresholds
    res=[]
    base=np.uint64(0)
    done=0
    while done<n_seeds:
        G=np.arange(int(base), int(base)+chunk, dtype=np.uint64); base+=chunk; done+=chunk
        s=step(G); slot_r=(s>>np.uint64(16))%np.uint64(100)
        slot=np.searchsorted(cums, slot_r, side='right').astype(np.int64)
        s=step(s)  # level
        s=step(s); nature=((s>>np.uint64(16))%np.uint64(25)).astype(np.int64)
        # nature-lock loop, vectorized
        matched=np.zeros(len(G),dtype=bool); pid=np.zeros(len(G),dtype=np.uint64); ivseed=np.zeros(len(G),dtype=np.uint64)
        cur=s.copy()
        for _ in range(maxloop):
            s1=step(cur); lo=s1>>np.uint64(16); s2=step(s1); hi=s2>>np.uint64(16)
            p=((hi<<np.uint64(16))|lo)&M
            nm=(~matched)&((p%np.uint64(25)).astype(np.int64)==nature)
            pid[nm]=p[nm]; ivseed[nm]=s2[nm]; matched|=nm
            cur=s2
            if matched.all(): break
        # shiny + mankey slot + physical nature + matched
        pl=pid&np.uint64(0xFFFF); ph=pid>>np.uint64(16)
        shiny=((xb^ph^pl)&np.uint64(0xFFFF))<np.uint64(8)
        mank=(slot==1)|(slot==3)
        phys=PHYS[nature]
        keep=matched&shiny&mank&phys
        idx=np.nonzero(keep)[0]
        if idx.size:
            # predicted IVs (gap0): iv1 from step(ivseed), iv2 from step(step(ivseed))
            ivs=ivseed[idx]; iv1=(step(ivs)>>np.uint64(16))&np.uint64(0x7FFF); iv2=(step(step(ivs))>>np.uint64(16))&np.uint64(0x7FFF)
            atk=((iv1>>np.uint64(5))&np.uint64(31)).astype(int); spe=(iv2&np.uint64(31)).astype(int)
            for j,e in enumerate(idx):
                res.append((int(G[e]), int(nature[e]), int(atk[j]), int(spe[j])))
    return res

def main():
    mgba.log.silence()
    core=mgba.core.load_path(ROM); fb=mgba.image.Image(*core.desired_video_dimensions())
    core.set_video_buffer(fb); core.reset(); load_state_file(core,STATE)
    base=bytes(core.save_raw_state()); mem=core.memory; L,R=core.KEY_LEFT,core.KEY_RIGHT
    def emulate(V):
        core.load_raw_state(base); mem.u32[RNG]=V; bp=mem.u32[ENEMY]
        i=0
        while i<70:
            btn=L if i%2==0 else R
            for ph in range(3):
                core.set_keys(btn) if ph<2 else core.set_keys(); core.run_frame()
                if mem.u32[ENEMY]!=bp: i=999; break
            if i==999: break
            i+=1
        for _ in range(20): core.run_frame()
        mon=b"".join(mem.u32[ENEMY+4*k].to_bytes(4,"little") for k in range(25))
        pid=int.from_bytes(mon[0:4],"little"); otid=int.from_bytes(mon[4:8],"little")
        dec=decrypt_block(mon[0x20:0x20+48],pid,otid)
        return int.from_bytes(dec[0:2],"little"),pid,ivs_from_decrypted(dec).as_tuple()
    def shiny(pid): return ((TID^SID^(pid>>16)^(pid&0xFFFF))&0xFFFF)<8

    t0=time.time()
    cands=offline_candidates()
    t_off=time.time()-t0
    # rank: Atk31 first, then predicted Spe, then nature pref, then Atk+Spe
    cands.sort(key=lambda c:((c[2]==31), c[3], NAT[c[1]] in ("Jolly","Adamant"), c[2]), reverse=True)
    print("offline: %d shiny-Mankey-physical candidates in %.1fs (%.0f seeds/s)"%(len(cands),t_off,60_000_000/t_off))
    print("verifying best candidates in emulator...")
    t1=time.time(); verified=[]; checked=0
    for G,nat,patk,pspe in cands[:400]:
        V=rewind(G,GEN_OFFSET); sp,pid,iv=emulate(V); checked+=1
        if sp==56 and shiny(pid):
            verified.append((V,G,pid,iv)); 
            if iv[1]==31 and iv[3]>=29: break  # great Atk + Speed
    t_ver=time.time()-t1
    verified.sort(key=lambda v:((v[3][1]==31),(v[3][3]==31),v[3][1]+v[3][3],sum(v[3])),reverse=True)
    print("verified %d shiny Mankeys (checked %d) in %.1fs"%(len(verified),checked,t_ver))
    for V,G,pid,iv in verified[:8]:
        print("  write=0x%08X nature=%-8s IVs(H,A,D,Sp,SpA,SpD)=%s Atk+Spe=%d"%(V,NAT[pid%25],iv,iv[1]+iv[3]))
    if verified:
        bestV,G,pid,iv=verified[0]
        # reproduce + save state
        emulate(bestV)
        from pokemon_agent.gba_state import save_state_file
        save_state_file(core,"roms/leafgreen_shiny_mankey.ss1")
        print("BEST: write=0x%08X nature=%s IVs=%s -> saved roms/leafgreen_shiny_mankey.ss1"%(bestV,NAT[pid%25],iv))
    print("TIMING: offline %.1fs + verify %.1fs = %.1fs total"%(t_off,t_ver,t_off+t_ver))

if __name__=="__main__": main()
