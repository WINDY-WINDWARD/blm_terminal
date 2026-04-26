#!/usr/bin/env bash
# camoufox_setup.sh — one-time setup for camoufox headless news fetching
#
# Usage:
#   chmod +x camoufox_setup.sh
#   ./camoufox_setup.sh
#
# What this script does:
#   1. Activates the backend .venv (creates it if missing)
#   2. Installs / upgrades the camoufox[geoip] package
#   3. Downloads the camoufox Firefox binary  (camoufox fetch)
#   4. Installs Linux runtime dependencies    (libgtk-3-0, libx11-xcb1, libasound2)
#   5. Appends CAMOUFOX_ENABLED=true to .env.local if not already present
#
# Run this once.  After that, just start the backend normally with:
#   uvicorn main:app --reload --port 4455

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$SCRIPT_DIR/.venv"
ENV_LOCAL="$SCRIPT_DIR/.env.local"

# ── colours ──────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[camoufox-setup]${NC} $*"; }
warn()    { echo -e "${YELLOW}[camoufox-setup]${NC} $*"; }
error()   { echo -e "${RED}[camoufox-setup]${NC} $*" >&2; }

# ── 1. Activate / create venv ─────────────────────────────────────────────────
if [[ ! -d "$VENV_DIR" ]]; then
    info "No .venv found — creating one..."
    python3 -m venv "$VENV_DIR"
fi

info "Activating virtual environment..."
# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"

# ── 2. Install / upgrade camoufox ─────────────────────────────────────────────
info "Installing / upgrading camoufox[geoip]..."
pip install --quiet --upgrade "camoufox[geoip]>=0.4.0"

# ── 3. Download the camoufox Firefox binary ───────────────────────────────────
info "Fetching camoufox Firefox binary (this may take a while on first run)..."
python3 -m camoufox fetch

# ── 4. Install Linux runtime deps ─────────────────────────────────────────────
if command -v apt-get &>/dev/null; then
    info "Installing Firefox runtime libraries via apt..."
    sudo apt-get install -y --no-install-recommends \
        libgtk-3-0 \
        libx11-xcb1 \
        libasound2 2>/dev/null \
    || warn "apt install failed (may already be present, continuing)"
elif command -v pacman &>/dev/null; then
    info "Installing Firefox runtime libraries via pacman..."
    sudo pacman -S --noconfirm --needed gtk3 libx11 libxcb cairo alsa-lib \
    || warn "pacman install failed (may already be present, continuing)"
else
    warn "Unknown package manager — skipping runtime library install."
    warn "If camoufox fails to launch, manually install: libgtk-3, libx11-xcb, libasound2"
fi

# ── 5. Enable camoufox in .env.local ─────────────────────────────────────────
if [[ ! -f "$ENV_LOCAL" ]]; then
    warn ".env.local not found — creating it."
    touch "$ENV_LOCAL"
fi

if grep -qE '^\s*CAMOUFOX_ENABLED\s*=' "$ENV_LOCAL" 2>/dev/null; then
    # Key exists — make sure it's set to true (update in-place)
    sed -i 's/^\s*CAMOUFOX_ENABLED\s*=.*/CAMOUFOX_ENABLED=true/' "$ENV_LOCAL"
    info "Updated existing CAMOUFOX_ENABLED=true in .env.local"
else
    printf '\n# Camoufox headless Firefox for news fetching (set by camoufox_setup.sh)\nCAMOUFOX_ENABLED=true\n' >> "$ENV_LOCAL"
    info "Appended CAMOUFOX_ENABLED=true to .env.local"
fi

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
info "Setup complete."
info "camoufox binary path: $(python3 -m camoufox path 2>/dev/null || echo 'run: python3 -m camoufox path')"
echo ""
info "Start the backend as usual:"
info "  uvicorn main:app --reload --port 4455"
echo ""
info "To disable camoufox without uninstalling, set CAMOUFOX_ENABLED=false in .env.local"
