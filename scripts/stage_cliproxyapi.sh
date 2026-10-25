#!/usr/bin/env bash
# Pinned CLIProxyAPI downloader and staging script for macOS.
# Stages official CLIProxyAPI v8.0.39 to vendor/cliproxyapi/runtime/cliproxyapi.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${1:-${REPO_ROOT}/vendor/cliproxyapi/runtime}"
VERIFY_ONLY="${2:-}"

VERSION="v8.0.39"
ARCH="$(uname -m)"

if [ "${ARCH}" = "arm64" ] || [ "${ARCH}" = "aarch64" ]; then
    ASSET_NAME="CLIProxyAPI_8.0.39_darwin_aarch64.tar.gz"
    EXPECTED_SHA256="1febf0f15bef7cc70630496a4f5b145d1faafedf2c8bf0ae4d5648f0972b24be"
    EXPECTED_BINARY_SHA256="510a1f974a5b409bd9ee016d6f9ebcf6eb0b0f2a562858543d15af0e8deb5275"
elif [ "${ARCH}" = "x86_64" ]; then
    ASSET_NAME="CLIProxyAPI_8.0.39_darwin_amd64.tar.gz"
    EXPECTED_SHA256="1cb6ab8893811b5838d59b22a11bf4c9332cdbc40e66de18edbd4c926f2635ea"
    EXPECTED_BINARY_SHA256="f1fef944619f05781f06d2286610291565a5924c10a1beda650774e473555bb2"
else
    echo "Error: Unsupported architecture ${ARCH} on macOS" >&2
    exit 1
fi

TARGET_BIN="${TARGET_DIR}/cliproxyapi"
DOWNLOAD_URL="https://github.com/router-for-me/CLIProxyAPI/releases/download/${VERSION}/${ASSET_NAME}"

test_staged_binary() {
    [ -f "${TARGET_BIN}" ] && [ -x "${TARGET_BIN}" ] && [ "$(wc -c < "${TARGET_BIN}")" -gt 1000000 ] || return 1
    local actual_bin_hash
    if command -v shasum >/dev/null 2>&1; then
        actual_bin_hash="$(shasum -a 256 "${TARGET_BIN}" | awk '{print $1}')"
    else
        actual_bin_hash="$(sha256sum "${TARGET_BIN}" | awk '{print $1}')"
    fi
    [ "${actual_bin_hash}" = "${EXPECTED_BINARY_SHA256}" ]
}

if [ "${VERIFY_ONLY}" = "--verify-only" ] || [ "${VERIFY_ONLY}" = "-VerifyOnly" ]; then
    if test_staged_binary; then
        echo "CLIProxyAPI binary verified at: ${TARGET_BIN}"
        exit 0
    else
        if [ ! -f "${TARGET_BIN}" ]; then
            echo "Error: CLIProxyAPI binary is missing at: ${TARGET_BIN}" >&2
        else
            echo "Error: CLIProxyAPI binary failed checksum verification at: ${TARGET_BIN}" >&2
        fi
        exit 1
    fi
fi

if test_staged_binary; then
    echo "CLIProxyAPI binary already staged and verified at: ${TARGET_BIN}"
    exit 0
fi

echo "Staging CLIProxyAPI ${VERSION} for macOS (${ARCH})..."
mkdir -p "${TARGET_DIR}"

TMP_ARCHIVE="${TARGET_DIR}/download-${ASSET_NAME}.tmp"
trap 'rm -f "${TMP_ARCHIVE}"' EXIT

echo "Downloading ${DOWNLOAD_URL}..."
curl -sSL --fail -o "${TMP_ARCHIVE}" "${DOWNLOAD_URL}"

echo "Verifying archive SHA-256 checksum..."
if command -v shasum >/dev/null 2>&1; then
    ACTUAL_SHA256="$(shasum -a 256 "${TMP_ARCHIVE}" | awk '{print $1}')"
else
    ACTUAL_SHA256="$(sha256sum "${TMP_ARCHIVE}" | awk '{print $1}')"
fi

if [ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]; then
    echo "Error: Archive checksum mismatch for ${ASSET_NAME}!" >&2
    echo "Expected: ${EXPECTED_SHA256}" >&2
    echo "Actual:   ${ACTUAL_SHA256}" >&2
    exit 1
fi
echo "Archive checksum verified: ${ACTUAL_SHA256}"

echo "Extracting cli-proxy-api..."
tar -xzf "${TMP_ARCHIVE}" -C "${TARGET_DIR}" cli-proxy-api
EXTRACTED_BIN="${TARGET_DIR}/cli-proxy-api"

if command -v shasum >/dev/null 2>&1; then
    ACTUAL_EXTRACTED_HASH="$(shasum -a 256 "${EXTRACTED_BIN}" | awk '{print $1}')"
else
    ACTUAL_EXTRACTED_HASH="$(sha256sum "${EXTRACTED_BIN}" | awk '{print $1}')"
fi

if [ "${ACTUAL_EXTRACTED_HASH}" != "${EXPECTED_BINARY_SHA256}" ]; then
    echo "Error: Extracted binary checksum mismatch!" >&2
    echo "Expected: ${EXPECTED_BINARY_SHA256}" >&2
    echo "Actual:   ${ACTUAL_EXTRACTED_HASH}" >&2
    rm -f "${EXTRACTED_BIN}"
    exit 1
fi

mv -f "${EXTRACTED_BIN}" "${TARGET_BIN}"
chmod +x "${TARGET_BIN}"

echo "Successfully staged CLIProxyAPI at: ${TARGET_BIN}"