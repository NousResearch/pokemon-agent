//! Safe-ish emulator core: wraps `mgba::Core` and adds the memory + save-state
//! operations the hunt needs (the upstream wrapper omits them), via `raw_ptr()`.

use std::ffi::CString;
use std::path::Path;

use mgba::{mgba_sys, Core};
use pokemon_rng::decrypt::parse_enemy;
use pokemon_rng::Ivs;

/// `gRngValue` — the GBA RNG seed.
pub const RNG_ADDR: u32 = 0x0300_5000;
/// `gEnemyParty[0]` — the wild mon struct (100 bytes).
pub const ENEMY_ADDR: u32 = 0x0202_402C;
/// mGBA savestate flags (screenshot|savedata|cheats|rtc|metadata).
const SAVESTATE_ALL: i32 = 31;

const ROM_DEFAULT: &str = "roms/Pokemon - LeafGreen Version (USA).gba";

/// A loaded GBA core plus a cached clean snapshot to reset between triggers.
pub struct Emu {
    core: Core,
    base: Vec<u8>,
}

impl Emu {
    /// Load the ROM, load the `.ss1` save state, and snapshot it as the reset point.
    pub fn from_state(state: &Path) -> Result<Self, String> {
        Self::with_rom(Path::new(ROM_DEFAULT), state)
    }

    pub fn with_rom(rom: &Path, state: &Path) -> Result<Self, String> {
        let mut core = Core::new().map_err(|e| format!("core: {e}"))?;
        core.load_rom(rom)
            .map_err(|e| format!("load_rom {}: {e}", rom.display()))?;
        core.reset().map_err(|e| format!("reset: {e}"))?;
        let mut emu = Emu {
            core,
            base: Vec::new(),
        };
        if !emu.load_ss1(state) {
            return Err(format!("could not load save state {}", state.display()));
        }
        emu.base = emu.save_raw();
        Ok(emu)
    }

    #[inline]
    pub fn read32(&mut self, addr: u32) -> u32 {
        unsafe {
            let raw = self.core.raw_ptr();
            ((*raw).busRead32.expect("busRead32"))(raw, addr)
        }
    }

    #[inline]
    pub fn write32(&mut self, addr: u32, val: u32) {
        unsafe {
            let raw = self.core.raw_ptr();
            ((*raw).busWrite32.expect("busWrite32"))(raw, addr, val);
        }
    }

    #[inline]
    pub fn run_frame(&mut self) {
        self.core.run_frame().expect("run_frame");
    }

    #[inline]
    pub fn set_keys(&mut self, keys: u32) {
        self.core.set_keys(keys).expect("set_keys");
    }

    /// Snapshot the live state into a raw byte buffer (fast reset point).
    pub fn save_raw(&mut self) -> Vec<u8> {
        unsafe {
            let raw = self.core.raw_ptr();
            let size = ((*raw).stateSize.expect("stateSize"))(raw);
            let mut buf = vec![0u8; size];
            let ok = ((*raw).saveState.expect("saveState"))(raw, buf.as_mut_ptr() as *mut _);
            assert!(ok, "saveState failed");
            buf
        }
    }

    /// Restore a raw snapshot taken by [`save_raw`](Self::save_raw).
    pub fn load_raw(&mut self, buf: &[u8]) {
        unsafe {
            let raw = self.core.raw_ptr();
            let ok = ((*raw).loadState.expect("loadState"))(raw, buf.as_ptr() as *const _);
            assert!(ok, "loadState failed");
        }
    }

    /// Reset to the cached clean snapshot.
    pub fn reset_to_base(&mut self) {
        let base = std::mem::take(&mut self.base);
        self.load_raw(&base);
        self.base = base;
    }

    /// Load an mGBA `.ss1` save-state file (PNG or native) via libmgba's VFS.
    pub fn load_ss1(&mut self, path: &Path) -> bool {
        let c = match CString::new(path.to_string_lossy().as_bytes()) {
            Ok(c) => c,
            Err(_) => return false,
        };
        unsafe {
            let vf = mgba_sys::VFileOpen(c.as_ptr(), libc::O_RDONLY);
            if vf.is_null() {
                return false;
            }
            let raw = self.core.raw_ptr();
            let ok = mgba_sys::mCoreLoadStateNamed(raw, vf, SAVESTATE_ALL);
            ((*vf).close.expect("vf close"))(vf);
            ok
        }
    }

    /// Save the live state to an mGBA `.ss1` file (PNG) via libmgba's VFS.
    pub fn save_ss1(&mut self, path: &Path) -> bool {
        let c = match CString::new(path.to_string_lossy().as_bytes()) {
            Ok(c) => c,
            Err(_) => return false,
        };
        unsafe {
            let vf =
                mgba_sys::VFileOpen(c.as_ptr(), libc::O_WRONLY | libc::O_CREAT | libc::O_TRUNC);
            if vf.is_null() {
                return false;
            }
            let raw = self.core.raw_ptr();
            let ok = mgba_sys::mCoreSaveStateNamed(raw, vf, SAVESTATE_ALL);
            ((*vf).close.expect("vf close"))(vf);
            ok
        }
    }

    /// Read `gEnemyParty[0]` and decrypt it into (pid, ivs, species).
    pub fn read_enemy(&mut self) -> Option<(u32, Ivs, u16)> {
        let mut mon = [0u8; 100];
        for k in 0..25u32 {
            let w = self.read32(ENEMY_ADDR + 4 * k);
            mon[(4 * k) as usize..(4 * k + 4) as usize].copy_from_slice(&w.to_le_bytes());
        }
        parse_enemy(&mon)
    }

    #[inline]
    pub fn enemy_word(&mut self) -> u32 {
        self.read32(ENEMY_ADDR)
    }
}
