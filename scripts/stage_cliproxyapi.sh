#!/usr/bin/env bash
# Pinned CLIProxyAPI downloader and staging script for macOS.
# Stages official CLIProxyAPI from resources/cliproxyapi/PROVENANCE.json to vendor/cliproxyapi/runtime/cliproxyapi.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
TARGET_DIR="${1:-${REPO_ROOT}/vendor/cliproxyapi/runtime}"
VERIFY_ONLY="${2:-}"

PROVENANCE_FILE="${REPO_ROOT}/resources/cliproxyapi/PROVENANCE.json"
if [ ! -f "${PROVENANCE_FILE}" ]; then
    echo "Error: PROVENANCE.json is missing at ${PROVENANCE_FILE}" >&2
    exit 1
fi

if command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
else
    echo "Error: Python is required to parse PROVENANCE.json but neither python3 nor python was found." >&2
    exit 1
fi

ARCH="$(uname -m)"
if [ "${ARCH}" = "arm64" ] || [ "${ARCH}" = "aarch64" ]; then
    ARCH_KEY="darwin_arm64"
elif [ "${ARCH}" = "x86_64" ]; then
    ARCH_KEY="darwin_amd64"
else
    echo "Error: Unsupported architecture ${ARCH} on macOS" >&2
    exit 1
fi

PARSED_OUTPUT="$("${PYTHON_BIN}" -c '
import json, sys

path, arch_key = sys.argv[1], sys.argv[2]
try:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
except Exception as e:
    sys.stderr.write(f"Error: Failed to parse {path}: {e}\n")
    sys.exit(1)

version = data.get("version")
if not version:
    sys.stderr.write("Error: PROVENANCE.json is missing the required version field\n")
    sys.exit(1)

archs = data.get("architectures", {})
entry = archs.get(arch_key)
if not entry:
    sys.stderr.write(f"Error: PROVENANCE.json is missing architecture entry for {arch_key}\n")
    sys.exit(1)

fields = [
    str(version),
    str(entry.get("asset_name", "")),
    str(entry.get("download_url", "")),
    str(entry.get("sha256", "")),
    str(entry.get("binary_sha256", "")),
    str(entry.get("archive_binary_name", "cli-proxy-api")),
    str(entry.get("target_binary_name", "cliproxyapi")),
]

if not fields[0] or not fields[1] or not fields[2] or not fields[3] or not fields[4]:
    sys.stderr.write(f"Error: PROVENANCE.json entry for {arch_key} has missing required fields\n")
    sys.exit(1)

print("\t".join(fields))
' "${PROVENANCE_FILE}" "${ARCH_KEY}")"

IFS=$'\t' read -r VERSION ASSET_NAME DOWNLOAD_URL EXPECTED_SHA256 EXPECTED_BINARY_SHA256 ARCHIVE_BINARY_NAME TARGET_BINARY_NAME <<< "${PARSED_OUTPUT}"

TARGET_BIN="${TARGET_DIR}/${TARGET_BINARY_NAME}"

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
        echo "CLIProxyAPI ${VERSION} binary verified at: ${TARGET_BIN}"
        exit 0
    else
        if [ ! -f "${TARGET_BIN}" ]; then
            echo "Error: CLIProxyAPI ${VERSION} binary is missing at: ${TARGET_BIN}. Run scripts/stage_cliproxyapi.sh to stage it from PROVENANCE.json." >&2
        else
            echo "Error: CLIProxyAPI ${VERSION} binary failed checksum verification at: ${TARGET_BIN}" >&2
        fi
        exit 1
    fi
fi

if test_staged_binary; then
    echo "CLIProxyAPI ${VERSION} binary already staged and verified at: ${TARGET_BIN}"
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

echo "Extracting ${ARCHIVE_BINARY_NAME}..."
tar -xzf "${TMP_ARCHIVE}" -C "${TARGET_DIR}" "${ARCHIVE_BINARY_NAME}"
EXTRACTED_BIN="${TARGET_DIR}/${ARCHIVE_BINARY_NAME}"

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

echo "Successfully staged CLIProxyAPI ${VERSION} at: ${TARGET_BIN}"
