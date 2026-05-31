use std::env;
use std::path::PathBuf;

fn main() {
    let mgba_dir = PathBuf::from(env::var("CARGO_MANIFEST_DIR").unwrap()).join("mgba");

    // Rerun if the wrapper header or mgba source changes
    println!("cargo:rerun-if-changed=wrapper.h");
    println!("cargo:rerun-if-changed=mgba");

    // Check that cmake is available
    which("cmake");

    // Build libmgba with cmake - minimal configuration for headless GBA emulation
    let dst = cmake::Config::new(&mgba_dir)
        // Shared lib: avoids static-archive member-pull / gc-sections / whole-archive
        // fragility with rust-lld; all exported symbols resolve at runtime via rpath.
        .define("BUILD_SHARED", "ON")
        .define("BUILD_STATIC", "OFF")
        .define("BUILD_QT", "OFF")
        .define("BUILD_SDL", "OFF")
        .define("BUILD_GL", "OFF")
        .define("BUILD_GLES2", "OFF")
        .define("BUILD_GLES3", "OFF")
        .define("BUILD_LIBRETRO", "OFF")
        .define("BUILD_PERF", "OFF")
        .define("BUILD_TEST", "OFF")
        .define("BUILD_SUITE", "OFF")
        .define("BUILD_CINEMA", "OFF")
        .define("BUILD_HEADLESS", "OFF")
        .define("BUILD_EXAMPLE", "OFF")
        .define("BUILD_PYTHON", "OFF")
        .define("BUILD_DOCGEN", "OFF")
        .define("BUILD_MAINTAINER_TOOLS", "OFF")
        .define("ENABLE_DEBUGGERS", "OFF")
        .define("ENABLE_SCRIPTING", "OFF")
        .define("ENABLE_GDB_STUB", "OFF")
        .define("USE_FFMPEG", "OFF")
        // PNG ON: our .ss1 save states are PNG-wrapped mGBA savestates.
        .define("USE_PNG", "ON")
        .define("USE_LIBZIP", "OFF")
        .define("USE_SQLITE3", "OFF")
        .define("USE_ELF", "OFF")
        .define("USE_LUA", "OFF")
        .define("USE_JSON_C", "OFF")
        .define("USE_FREETYPE", "OFF")
        .define("USE_DISCORD_RPC", "OFF")
        .define("USE_EDITLINE", "OFF")
        .define("USE_LZMA", "OFF")
        .define("USE_MINIZIP", "OFF")
        .define("USE_EPOXY", "OFF")
        .define("M_CORE_GBA", "ON")
        .define("M_CORE_GB", "OFF")
        .define("DISABLE_DEPS", "OFF")
        .define("USE_ZLIB", "ON")
        .build();

    // Link the shared library (Fedora installs to lib64, others to lib) and embed
    // an rpath so the binary finds libmgba.so at runtime.
    for sub in ["lib", "lib64"] {
        println!("cargo:rustc-link-search=native={}/{sub}", dst.display());
        println!("cargo:rustc-link-arg=-Wl,-rpath,{}/{sub}", dst.display());
    }
    println!("cargo:rustc-link-lib=dylib=mgba");

    // Copy libmgba.so* next to the final binaries/tests so the $ORIGIN rpath (set in
    // .cargo/config) resolves it at runtime, regardless of the per-build hash dir.
    let out = PathBuf::from(env::var("OUT_DIR").unwrap());
    let profile_dir = out.ancestors().nth(3).unwrap().to_path_buf(); // target/<profile>
    for sub in ["lib", "lib64"] {
        let src = dst.join(sub);
        if src.is_dir() {
            for dest in [profile_dir.clone(), profile_dir.join("deps")] {
                let _ = std::fs::create_dir_all(&dest);
                if let Ok(entries) = std::fs::read_dir(&src) {
                    for e in entries.flatten() {
                        let name = e.file_name();
                        if name.to_string_lossy().contains("libmgba.so") {
                            let _ = std::fs::copy(e.path(), dest.join(&name));
                        }
                    }
                }
            }
        }
    }

    // Link system libraries needed by mgba
    let target_os = env::var("CARGO_CFG_TARGET_OS").unwrap();
    match target_os.as_str() {
        "macos" => {
            println!("cargo:rustc-link-lib=framework=CoreFoundation");
            println!("cargo:rustc-link-lib=z");
        }
        "linux" => {
            println!("cargo:rustc-link-lib=z");
            println!("cargo:rustc-link-lib=m");
            println!("cargo:rustc-link-lib=rt");
            // libmgba built with USE_PNG references libpng.
            println!("cargo:rustc-link-lib=png");
        }
        "windows" => {
            println!("cargo:rustc-link-lib=ws2_32");
            println!("cargo:rustc-link-lib=shlwapi");
            println!("cargo:rustc-link-lib=z");
        }
        _ => {}
    }

    // Generate bindings with bindgen
    let include_dir = mgba_dir.join("include");
    let generated_include_dir = dst.join("include");

    let bindings = bindgen::Builder::default()
        .header("wrapper.h")
        .clang_arg(format!("-I{}", include_dir.display()))
        .clang_arg(format!("-I{}", generated_include_dir.display()))
        // Feature defines that match what cmake enables
        .clang_arg("-DENABLE_VFS")
        .clang_arg("-DENABLE_VFS_FD")
        .clang_arg("-DENABLE_DIRECTORIES")
        .clang_arg("-DM_CORE_GBA")
        .clang_arg("-DUSE_ZLIB")
        // Core types
        .allowlist_type("mCore")
        .allowlist_type("mPlatform")
        .allowlist_type("mColorFormat")
        .allowlist_type("mCoreCallbacks")
        .allowlist_type("mAVStream")
        .allowlist_type("mAudioBuffer")
        .allowlist_type("mStereoSample")
        .allowlist_type("mCoreConfig")
        .allowlist_type("mCoreOptions")
        .allowlist_type("GBAKey")
        .allowlist_type("GBASavedataType")
        .allowlist_type("VFile")
        .allowlist_type("VDir")
        // Core functions
        .allowlist_function("mCoreFind")
        .allowlist_function("mCoreFindVF")
        .allowlist_function("mCoreLoadFile")
        .allowlist_function("mCoreAutoloadSave")
        .allowlist_function("mCoreAutoloadPatch")
        .allowlist_function("mCoreInitConfig")
        .allowlist_function("mCoreLoadConfig")
        .allowlist_function("mCoreConfigInit")
        .allowlist_function("mCoreConfigDeinit")
        .allowlist_function("mCoreConfigLoadDefaults")
        .allowlist_function("GBACoreCreate")
        // Audio buffer functions
        .allowlist_function("mAudioBufferInit")
        .allowlist_function("mAudioBufferDeinit")
        .allowlist_function("mAudioBufferAvailable")
        .allowlist_function("mAudioBufferCapacity")
        .allowlist_function("mAudioBufferClear")
        .allowlist_function("mAudioBufferRead")
        .allowlist_function("mAudioBufferWrite")
        // VFS functions
        .allowlist_function("VFileOpen")
        .allowlist_function("VFileFOpen")
        .allowlist_function("VFileFromMemory")
        // Savestate file I/O (PNG/native) — needed to load our .ss1 states
        .allowlist_function("mCoreLoadStateNamed")
        .allowlist_function("mCoreSaveStateNamed")
        // Log functions
        .allowlist_function("mLogSetDefaultLogger")
        .allowlist_function("mLogFilterInit")
        .allowlist_function("mLogFilterDeinit")
        // Version info
        .allowlist_var("gitCommit")
        .allowlist_var("gitCommitShort")
        .allowlist_var("projectVersion")
        .allowlist_var("projectName")
        // Constants
        .allowlist_var("GBA_VIDEO_HORIZONTAL_PIXELS")
        .allowlist_var("GBA_VIDEO_VERTICAL_PIXELS")
        // Derive traits
        .derive_debug(true)
        .derive_default(true)
        .prepend_enum_name(false)
        .generate_comments(false)
        .layout_tests(false)
        .generate()
        .expect("failed to generate bindings");

    let out_path = PathBuf::from(env::var("OUT_DIR").unwrap());
    bindings
        .write_to_file(out_path.join("bindings.rs"))
        .expect("failed to write bindings");
}

fn which(cmd: &str) {
    let status = std::process::Command::new("which")
        .arg(cmd)
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .status();
    match status {
        Ok(s) if s.success() => {}
        _ => {
            eprintln!("error: `{}` not found in PATH. Please install it.", cmd);
            eprintln!("  macOS:  brew install cmake");
            eprintln!("  Ubuntu: sudo apt install cmake");
            std::process::exit(1);
        }
    }
}
