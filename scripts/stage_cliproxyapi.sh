#!/usr/bin/env bash
# Pinned CLIProxyAPI downloader and staging script for macOS.
# Stages official CLIProxyAPI v8.0.35 to vendor/cliproxyapi/runtime/cliproxyapi.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${1:-${REPO_ROOT}/vendor/cliproxyapi/runtime}"
VERIFY_ONLY="${2:-}"

VERSION="v8.0.35"
ARCH="$(uname -m)"

if [ "${ARCH}" = "arm64" ] || [ "${ARCH}" = "aarch64" ]; then
    ASSET_NAME="CLIProxyAPI_8.0.35_darwin_aarch64.tar.gz"
    EXPECTED_SHA256="b6903000ae78b541e5ba0bb2db45fc15dc23cab77fb51ed4b02e03ea18fe36a5"
elif [ "${ARCH}" = "x86_64" ]; then
    ASSET_NAME="CLIProxyAPI_8.0.35_darwin_amd64.tar.gz"
    EXPECTED_SHA256="c1335ddb5307d67684ec0531fac81e1148b68869179310ea0f4086109fbebe2b"
else
    echo "Error: Unsupported architecture ${ARCH} on macOS" >&2
    exit 1
fi

TARGET_BIN="${TARGET_DIR}/cliproxyapi"
DOWNLOAD_URL="https://github.com/router-for-me/CLIProxyAPI/releases/download/${VERSION}/${ASSET_NAME}"

test_staged_binary() {
    [ -f "${TARGET_BIN}" ] && [ -x "${TARGET_BIN}" ] && [ "$(wc -c < "${TARGET_BIN}")" -gt 1000000 ]
}

if [ "${VERIFY_ONLY}" = "--verify-only" ] || [ "${VERIFY_ONLY}" = "-VerifyOnly" ]; then
    if test_staged_binary; then
        echo "CLIProxyAPI binary verified at: ${TARGET_BIN}"
        exit 0
    else
        echo "Error: CLIProxyAPI binary is missing or invalid at: ${TARGET_BIN}" >&2
        exit 1
    fi
fi

if test_staged_binary; then
    echo "CLIProxyAPI binary already staged at: ${TARGET_BIN}"
    exit 0
fi

echo "Staging CLIProxyAPI ${VERSION} for macOS (${ARCH})..."
mkdir -p "${TARGET_DIR}"

TMP_ARCHIVE="${TARGET_DIR}/download-${ASSET_NAME}.tmp"
trap 'rm -f "${TMP_ARCHIVE}"' EXIT

echo "Downloading ${DOWNLOAD_URL}..."
curl -sSL --fail -o "${TMP_ARCHIVE}" "${DOWNLOAD_URL}"

echo "Verifying SHA-256 checksum..."
if command -v shasum >/dev/null 2>&1; then
    ACTUAL_SHA256="$(shasum -a 256 "${TMP_ARCHIVE}" | awk '{print $1}')"
else
    ACTUAL_SHA256="$(sha256sum "${TMP_ARCHIVE}" | awk '{print $1}')"
fi

if [ "${ACTUAL_SHA256}" != "${EXPECTED_SHA256}" ]; then
    echo "Error: Checksum mismatch for ${ASSET_NAME}!" >&2
    echo "Expected: ${EXPECTED_SHA256}" >&2
    echo "Actual:   ${ACTUAL_SHA256}" >&2
    exit 1
fi
echo "Checksum verified: ${ACTUAL_SHA256}"

echo "Extracting cli-proxy-api..."
tar -xzf "${TMP_ARCHIVE}" -C "${TARGET_DIR}" cli-proxy-api
mv -f "${TARGET_DIR}/cli-proxy-api" "${TARGET_BIN}"
chmod +x "${TARGET_BIN}"

echo "Successfully staged CLIProxyAPI at: ${TARGET_BIN}"
