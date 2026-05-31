//! Safe Rust wrapper around [libmgba](https://mgba.io/) for GBA emulation.
//!
//! This crate provides a high-level [`Core`] type that manages the lifecycle of
//! a GBA emulator instance, including video rendering, audio output, and input.
//!
//! # Example
//!
//! ```no_run
//! use mgba::Core;
//! use std::path::Path;
//!
//! let mut core = Core::new().expect("failed to create core");
//! core.load_rom(Path::new("game.gba")).expect("failed to load ROM");
//! core.reset().expect("reset failed");
//!
//! // Run one frame
//! core.run_frame().expect("run_frame failed");
//!
//! // Read the framebuffer (240x160 XBGR8 pixels)
//! let pixels = core.video_buffer();
//! ```

// Re-export the raw FFI crate so downstream users link a SINGLE mgba-sys unit
// (avoids a duplicate build that breaks whole-archive linking of libmgba).
pub use mgba_sys;

use std::ffi::CString;
use std::fmt;
use std::marker::PhantomData;
use std::path::Path;
use std::sync::OnceLock;

extern "C" {
    fn free(ptr: *mut std::ffi::c_void);
}

/// GBA screen width in pixels.
pub const GBA_WIDTH: usize = 240;
/// GBA screen height in pixels.
pub const GBA_HEIGHT: usize = 160;
/// Total number of pixels in a GBA frame (`GBA_WIDTH * GBA_HEIGHT`).
pub const GBA_PIXELS: usize = GBA_WIDTH * GBA_HEIGHT;
/// Native GBA audio sample rate in Hz.
pub const GBA_SAMPLE_RATE: u32 = 32768;

/// GBA input buttons.
///
/// Each variant corresponds to a physical button on the Game Boy Advance.
/// Use [`Key::mask`] to get the bitmask for a key, suitable for passing
/// to [`Core::set_keys`].
#[repr(u32)]
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Key {
    A = 0,
    B = 1,
    Select = 2,
    Start = 3,
    Right = 4,
    Left = 5,
    Up = 6,
    Down = 7,
    R = 8,
    L = 9,
}

impl Key {
    /// All GBA keys in button order.
    pub const ALL: [Key; 10] = [
        Key::A,
        Key::B,
        Key::Select,
        Key::Start,
        Key::Right,
        Key::Left,
        Key::Up,
        Key::Down,
        Key::R,
        Key::L,
    ];

    /// Return the bitmask for this key (bit `N` set, where `N` is the key index).
    pub fn mask(self) -> u32 {
        1 << (self as u32)
    }
}

impl fmt::Display for Key {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(match self {
            Key::A => "A",
            Key::B => "B",
            Key::Select => "Select",
            Key::Start => "Start",
            Key::Right => "Right",
            Key::Left => "Left",
            Key::Up => "Up",
            Key::Down => "Down",
            Key::R => "R",
            Key::L => "L",
        })
    }
}

/// A GBA emulator core backed by libmgba.
///
/// `Core` is [`Send`] (it can be moved to another thread) but **not** [`Sync`]
/// — the underlying C state is single-threaded and must not be accessed from
/// multiple threads concurrently.
pub struct Core {
    raw: *mut mgba_sys::mCore,
    video_buffer: Box<[u32; GBA_PIXELS]>,
    loaded: bool,
    // Make Core !Sync — raw pointer to single-threaded C state.
    _not_sync: PhantomData<*const ()>,
}

// Safety: The mCore API is single-threaded, but we need Send to move it
// to the emulation thread. We ensure only one thread accesses it at a time.
unsafe impl Send for Core {}

// Wrapper so we can store mLogger in a OnceLock (requires Sync).
// Safety: The logger struct contains a function pointer and a null filter
// pointer. It is only written once and then read-only, which is safe across threads.
struct SyncLogger(mgba_sys::mLogger);
unsafe impl Sync for SyncLogger {}
unsafe impl Send for SyncLogger {}

static LOGGER: OnceLock<SyncLogger> = OnceLock::new();

/// No-op log callback that discards all messages.
unsafe extern "C" fn noop_log(
    _logger: *mut mgba_sys::mLogger,
    _category: std::os::raw::c_int,
    _level: mgba_sys::mLogLevel,
    _format: *const std::os::raw::c_char,
    _args: *mut mgba_sys::__va_list_tag,
) {
}

fn silence_mgba_logger() {
    let logger = LOGGER.get_or_init(|| {
        SyncLogger(mgba_sys::mLogger {
            log: Some(noop_log),
            filter: std::ptr::null_mut(),
        })
    });
    // Safety: the logger is initialized once and lives for 'static.
    // We cast away the const because the C API takes *mut, but mLogSetDefaultLogger
    // only stores the pointer — it does not mutate the struct.
    unsafe {
        mgba_sys::mLogSetDefaultLogger(&logger.0 as *const mgba_sys::mLogger as *mut _);
    }
}

impl Core {
    /// Create a new GBA core with the default port name `"mgba"`.
    ///
    /// This allocates and initializes the underlying libmgba core. Call
    /// [`load_rom`](Core::load_rom) followed by [`reset`](Core::reset) before
    /// running emulation.
    pub fn new() -> Result<Self, CoreError> {
        Self::with_port("mgba")
    }

    /// Create a new GBA core with a custom port name.
    ///
    /// The port name is used by libmgba for configuration file naming.
    pub fn with_port(port: &str) -> Result<Self, CoreError> {
        silence_mgba_logger();

        let port_c = CString::new(port).map_err(|_| CoreError::InvalidPath)?;

        unsafe {
            let raw = mgba_sys::GBACoreCreate();
            if raw.is_null() {
                return Err(CoreError::CreateFailed);
            }

            let init_fn = match (*raw).init {
                Some(f) => f,
                None => {
                    free(raw as *mut std::ffi::c_void);
                    return Err(CoreError::CreateFailed);
                }
            };
            if !init_fn(raw) {
                free(raw as *mut std::ffi::c_void);
                return Err(CoreError::InitFailed);
            }

            // Initialize the config system — required before loading ROMs
            mgba_sys::mCoreInitConfig(raw, port_c.as_ptr());

            let mut core = Core {
                raw,
                video_buffer: Box::new([0u32; GBA_PIXELS]),
                loaded: false,
                _not_sync: PhantomData,
            };

            // Set the video buffer
            let set_video = (*raw).setVideoBuffer.ok_or(CoreError::InitFailed)?;
            set_video(raw, core.video_buffer.as_mut_ptr(), GBA_WIDTH);

            Ok(core)
        }
    }

    /// Get a vtable function pointer, returning [`CoreError::MissingFunction`] if null.
    unsafe fn vtable<F>(&self, f: Option<F>) -> Result<F, CoreError> {
        f.ok_or(CoreError::MissingFunction)
    }

    /// Load a ROM from a file path.
    ///
    /// After loading, call [`reset`](Core::reset) to initialize the emulated GBA.
    pub fn load_rom(&mut self, path: &Path) -> Result<(), CoreError> {
        let path_str = path.to_str().ok_or(CoreError::InvalidPath)?;
        let c_path = CString::new(path_str).map_err(|_| CoreError::InvalidPath)?;

        unsafe {
            if !mgba_sys::mCoreLoadFile(self.raw, c_path.as_ptr()) {
                return Err(CoreError::RomLoadFailed);
            }

            // Autoload save file if it exists
            mgba_sys::mCoreAutoloadSave(self.raw);
        }

        self.loaded = true;
        Ok(())
    }

    /// Returns `true` if a ROM has been successfully loaded.
    pub fn is_loaded(&self) -> bool {
        self.loaded
    }

    /// Reset the core (must be called after loading a ROM).
    pub fn reset(&mut self) -> Result<(), CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).reset)?;
            f(self.raw);
        }
        Ok(())
    }

    /// Run one frame of emulation.
    pub fn run_frame(&mut self) -> Result<(), CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).runFrame)?;
            f(self.raw);
        }
        Ok(())
    }

    /// Set the key input state (bitmask of [`Key`] values).
    ///
    /// Build the bitmask by OR-ing together [`Key::mask`] values for each
    /// pressed button.
    pub fn set_keys(&mut self, keys: u32) -> Result<(), CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).setKeys)?;
            f(self.raw, keys);
        }
        Ok(())
    }

    /// Get the video buffer as a slice of XBGR8 pixels.
    ///
    /// Each pixel is a `u32` in `0x00BBGGRR` format (X = unused, B = blue,
    /// G = green, R = red). The buffer is 240x160 pixels in row-major order.
    pub fn video_buffer(&self) -> &[u32; GBA_PIXELS] {
        &self.video_buffer
    }

    /// Get the audio sample rate reported by the core.
    ///
    /// This is typically [`GBA_SAMPLE_RATE`] (32768 Hz).
    pub fn audio_sample_rate(&self) -> Result<u32, CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).audioSampleRate)?;
            Ok(f(self.raw))
        }
    }

    /// Read available audio samples into `out`.
    ///
    /// Audio data is stereo interleaved `i16` at [`GBA_SAMPLE_RATE`] Hz
    /// (left, right, left, right, ...). The `out` slice should have room
    /// for at least `2 * N` elements to read `N` stereo sample pairs.
    ///
    /// Returns the number of stereo sample pairs actually read.
    pub fn read_audio_samples(&mut self, out: &mut [i16]) -> Result<usize, CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).getAudioBuffer)?;
            let audio_buf = f(self.raw);
            if audio_buf.is_null() {
                return Ok(0);
            }
            let available = mgba_sys::mAudioBufferAvailable(audio_buf);
            let to_read = available.min(out.len() / 2); // stereo: 2 samples per pair
            if to_read == 0 {
                return Ok(0);
            }
            Ok(mgba_sys::mAudioBufferRead(
                audio_buf,
                out.as_mut_ptr(),
                to_read,
            ))
        }
    }

    /// Get the number of available stereo sample pairs in the audio buffer.
    pub fn audio_available(&self) -> Result<usize, CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).getAudioBuffer)?;
            let audio_buf = f(self.raw);
            if audio_buf.is_null() {
                return Ok(0);
            }
            Ok(mgba_sys::mAudioBufferAvailable(audio_buf))
        }
    }

    /// Set the audio buffer size (in stereo sample pairs).
    pub fn set_audio_buffer_size(&mut self, samples: usize) -> Result<(), CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).setAudioBufferSize)?;
            f(self.raw, samples);
        }
        Ok(())
    }

    /// Get the frame counter (number of frames emulated since last reset).
    pub fn frame_counter(&self) -> Result<u32, CoreError> {
        unsafe {
            let f = self.vtable((*self.raw).frameCounter)?;
            Ok(f(self.raw))
        }
    }

    /// Get the raw `mCore` pointer for advanced usage.
    ///
    /// # Safety
    ///
    /// The caller must not use this pointer to violate the aliasing guarantees
    /// of the safe wrapper, nor call it from multiple threads concurrently.
    pub unsafe fn raw_ptr(&mut self) -> *mut mgba_sys::mCore {
        self.raw
    }
}

impl Drop for Core {
    fn drop(&mut self) {
        unsafe {
            if !self.raw.is_null() {
                mgba_sys::mCoreConfigDeinit(&mut (*self.raw).config);
                if let Some(deinit_fn) = (*self.raw).deinit {
                    deinit_fn(self.raw);
                }
            }
        }
    }
}

/// Errors that can occur when using the GBA [`Core`].
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
#[non_exhaustive]
pub enum CoreError {
    /// Failed to allocate the GBA core.
    CreateFailed,
    /// Core initialization returned false.
    InitFailed,
    /// The provided path is not valid UTF-8 or contains a null byte.
    InvalidPath,
    /// libmgba could not load the ROM file.
    RomLoadFailed,
    /// A required vtable function pointer was null.
    MissingFunction,
}

impl fmt::Display for CoreError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            CoreError::CreateFailed => write!(f, "failed to create GBA core"),
            CoreError::InitFailed => write!(f, "failed to initialize GBA core"),
            CoreError::InvalidPath => write!(f, "invalid ROM path"),
            CoreError::RomLoadFailed => write!(f, "failed to load ROM"),
            CoreError::MissingFunction => write!(f, "missing core vtable function"),
        }
    }
}

impl std::error::Error for CoreError {}
