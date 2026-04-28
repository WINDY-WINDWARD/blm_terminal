#!/usr/bin/env bash
# cleanup_camoufox.sh — Remove camoufox and its dependencies from the project
#
# Usage:
#   chmod +x cleanup_camoufox.sh
#   ./cleanup_camoufox.sh
#
# What this script does:
#   1. Removes camoufox_setup.sh (if exists)
#   2. Removes test_camoufox.py (if exists)
#   3. Uninstalls camoufox and playwright from the venv
#   4. Removes CAMOUFOX_ENABLED from .env.local (if present)
#   5. Optionally removes camoufox Firefox binary cache (~/.cache/camoufox/)
#
# Run this script from the backend/ directory.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# ── colours ───────────────────────────────────────────────────────────────────
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info()    { echo -e "${GREEN}[cleanup]${NC} $*"; }
warn()    { echo -e "${YELLOW}[cleanup]${NC} $*"; }
error()  { echo -e "${RED}[cleanup]${NC} $*" >&2; }

# ── 1. Remove camoufox_setup.sh ───────────────────────────────────────────────
if [[ -f "camoufox_setup.sh" ]]; then
    info "Removing camoufox_setup.sh..."
    rm -f camoufox_setup.sh
    info "camoufox_setup.sh removed."
else
    info "camoufox_setup.sh not found (already clean)."
fi

# ── 2. Remove test_camoufox.py ──────────────────────────────────────────────
if [[ -f "test_camoufox.py" ]]; then
    info "Removing test_camoufox.py..."
    rm -f test_camoufox.py
    info "test_camoufox.py removed."
else
    info "test_camoufox.py not found (already clean)."
fi

# ── 3. Uninstall camoufox and playwright from venv ─────────────────────────
VENV_DIR="$SCRIPT_DIR/.venv"

if [[ ! -d "$VENV_DIR" ]]; then
    warn "No .venv found — skipping package uninstall."
else
    info "Activating virtual environment..."
    # shellcheck disable=SC1091
    source "$VENV_DIR/bin/activate"

    info "Uninstalling camoufox and playwright..."
    pip uninstall -y camoufox playwright 2>/dev/null || warn "camoufox/playwright not found in venv (may already be removed)"
    info "Package uninstall complete."
fi

# ── 4. Clean .env.local of CAMOUFOX_ENABLED ──────────────────────────────
ENV_LOCAL="$SCRIPT_DIR/.env.local"

if [[ -f "$ENV_LOCAL" ]]; then
    if grep -qE '^\s*CAMOUFOX_ENABLED\s*=' "$ENV_LOCAL" 2>/dev/null; then
        info "Removing CAMOUFOX_ENABLED from .env.local..."
        sed -i '/CAMOUFOX_ENABLED/d' "$ENV_LOCAL"
        info ".env.local cleaned."
    else
        info ".env.local found but no CAMOUFOX_ENABLED entry (already clean)."
    fi
else
    info ".env.local not found (nothing to clean)."
fi

# ── 5. Optionally remove camoufox Firefox binary cache ─────────────────────
CAMOUFOX_CACHE="$HOME/.cache/camoufox"

if [[ -d "$CAMOUFOX_CACHE" ]]; then
    warn "camoufox Firefox binary cache found at: $CAMOUFOX_CACHE"
    read -r -p "Remove camoufox cache? [y/N] " answer
    if [[ "$answer" =~ ^[Yy]$ ]]; then
        info "Removing camoufox cache..."
        rm -rf "$CAMOUFOX_CACHE"
        info "camoufox cache removed."
    else
        warn "Skipping cache removal."
    fi
else
    info "No camoufox cache found (already clean)."
fi

# ── Done ────────────────────────────────────────────────────────────────────
echo ""
info "Cleanup complete."
info "Your codebase is now free of camoufox."
echo ""
