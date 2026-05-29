#!/usr/bin/env bash
# Build mGBA 0.10.3 + its Python (cffi) bindings for the GBA shiny scripts.
#
# This is meant to run INSIDE the `devbox` distrobox (Fedora 41), NOT on the
# host — it keeps the host clean and gives us passwordless sudo for -devel
# packages.  From the host:
#
#     distrobox enter devbox -- bash /var/home/karce/Projects/pokemon-agent/scripts/build_mgba.sh
#
# What it produces:
#   * /usr/local/... libmgba (best-effort `make install`; may fail on a
#     read-only toolbox path — harmless, the bindings use an rpath instead)
#   * the `mgba` Python package installed into .venv-gba (Python 3.12)
#   * `pygba` installed into .venv-gba
#
# Re-running is safe; it rebuilds from a clean build dir.
set -euo pipefail

REPO=/var/home/karce/Projects/pokemon-agent
VENV="$REPO/.venv-gba"
SRC="$HOME/src/mgba"
MGBA_TAG=0.10.3

# GCC 14 (Fedora 41) promotes these to errors; the cffi-generated lib.c trips
# the va_list-vs-void* mLogger check, so relax them back to warnings.
RELAX_CFLAGS="-Wno-error=incompatible-pointer-types -Wno-error=implicit-function-declaration"

echo "==> [1/6] system build dependencies"
sudo dnf install -y \
    cmake make gcc gcc-c++ git pkg-config \
    libpng-devel libzip-devel zlib-ng-devel \
    ffmpeg-free-devel \
    python3.12 python3.12-devel

echo "==> [2/6] python venv (3.12) + build helpers"
if [ ! -x "$VENV/bin/python" ]; then
    python3.12 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip wheel setuptools
"$VENV/bin/pip" install -q "cffi>=1.6" pytest-runner cached-property numpy pillow

echo "==> [3/6] clone mGBA $MGBA_TAG"
mkdir -p "$(dirname "$SRC")"
if [ ! -d "$SRC" ]; then
    git clone --depth 1 --branch "$MGBA_TAG" https://github.com/mgba-emu/mgba.git "$SRC"
fi

echo "==> [4/6] configure (headless: no Qt/SDL/GL; ffmpeg ON so the python"
echo "          bindings' EReader symbols resolve; pinned to the venv 3.12)"
cd "$SRC"
rm -rf build && mkdir build && cd build
cmake .. \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_C_FLAGS="$RELAX_CFLAGS" \
    -DBUILD_PYTHON=ON \
    -DUSE_PYTHON_VERSION=3.12 \
    -DPYTHON_EXECUTABLE="$VENV/bin/python" \
    -DPYTHON_LIBRARY=/usr/lib64/libpython3.12.so \
    -DPYTHON_INCLUDE_DIR=/usr/include/python3.12 \
    -DBUILD_QT=OFF -DBUILD_SDL=OFF -DUSE_DISCORD_RPC=OFF \
    -DBUILD_GL=OFF -DBUILD_GLES2=OFF -DBUILD_GLES3=OFF -DUSE_EDITLINE=OFF \
    -DUSE_FFMPEG=ON

echo "==> [5/6] build libmgba + python bindings"
export CFLAGS="$RELAX_CFLAGS"   # setuptools/cffi build doesn't see CMAKE_C_FLAGS
make -j"$(nproc)"
sudo make install || echo "  (note: make install failed — harmless; rpath is used)"
sudo ldconfig || true

echo "==> [6/6] build wheel, install mgba + pygba into the venv"
make mgba-py-bdist
WHL=$(find "$SRC" -name "mgba-*.whl" | head -1)
"$VENV/bin/pip" install -q --force-reinstall --no-deps "$WHL"
"$VENV/bin/pip" install -q pygba   # mgba dep already satisfied → pulls pygame/gymnasium wheels

echo "==> verify"
cd "$REPO"
"$VENV/bin/python" - <<'PY' 2>/dev/null
import mgba.log; mgba.log.silence()
from pygba import PyGBA
gba = PyGBA.load("roms/Pokemon - LeafGreen Version (USA).gba")
gba.wait(30)
assert gba.read_u8(0x02000000) is not None
print("OK: mgba + pygba working in .venv-gba")
PY
echo "==> done."
