#!/bin/bash
# One signed full release; no base-plus-patch chain and no embedded credentials.
set -euo pipefail
umask 077
bnn_destination="${1:?Usage: bash download.sh /new/download/folder [--metadata-only]}"
bnn_metadata_only="${2:-}"
[[ -z "$bnn_metadata_only" || "$bnn_metadata_only" == --metadata-only ]] || exit 2
bnn_repository="${HERMES_BNN_REPOSITORY:-olegeklepikov-collab/hermes-bnn-full}"
bnn_tag="${HERMES_BNN_TAG:-bnn-2026.11.15}"
[[ "$bnn_repository" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ && "$bnn_tag" =~ ^[A-Za-z0-9_.-]+$ ]] || exit 2
bnn_script_root="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
[[ -f "$bnn_script_root/trust/allowed_signers" ]] || { echo 'Clone the source repository with its trust/ directory first.' >&2; exit 2; }
mkdir -p "$bnn_destination"
cd "$bnn_destination"
bnn_fetch() {
 local name="$1"
 [[ "$name" =~ ^[A-Za-z0-9_.-]+$ && "$name" != .* ]] || return 2
 [[ -f "$name" && ! -L "$name" ]] && return 0
 [[ ! -e "$name" && ! -L "$name" && ! -e "$name.downloading" && ! -L "$name.downloading" ]] || { echo "Existing unverified output: $name" >&2; return 3; }
 if [[ "$bnn_repository" == *-private ]]; then
  command -v gh >/dev/null || { echo 'Private repository: authenticate gh first, or use the public full repository.' >&2; return 2; }
  local temporary; temporary="$(mktemp -d .bnn-download.XXXXXX)"
  if ! gh release download "$bnn_tag" --repo "$bnn_repository" --pattern "$name" --dir "$temporary"; then return 4; fi
  [[ -f "$temporary/$name" && ! -L "$temporary/$name" ]] || return 4
  mv "$temporary/$name" "$name.downloading"
  rmdir "$temporary"
 else
  curl --http1.1 --fail --location --retry 1 --proto '=https' --proto-redir '=https' --tlsv1.2 --output "$name.downloading" "https://github.com/$bnn_repository/releases/download/$bnn_tag/$name"
 fi
 mv "$name.downloading" "$name"
}
bnn_json() { /usr/bin/plutil -extract "$2" raw -o - "$1" 2>/dev/null; }
bnn_verify_file() {
 local expected="$1" name="$2" bytes="$3"
 [[ "$expected" =~ ^[a-f0-9]{64}$ && "$bytes" =~ ^[0-9]+$ && -f "$name" && ! -L "$name" ]] || return 3
 [[ "$(stat -f '%z' "$name")" == "$bytes" ]] || return 3
 printf '%s  %s\n' "$expected" "$name" | shasum -a 256 -c -
}
for bnn_name in RELEASE.json RELEASE.json.sig PARTS.json PARTS.json.sig allowed_signers; do bnn_fetch "$bnn_name"; done
cmp allowed_signers "$bnn_script_root/trust/allowed_signers"
for bnn_name in RELEASE.json PARTS.json; do
 ssh-keygen -Y verify -f "$bnn_script_root/trust/allowed_signers" -I bnn-release -n bnn-release-v1 -s "$bnn_name.sig" < "$bnn_name"
done
[[ "$(bnn_json RELEASE.json owner_data_included)" == false && "$(bnn_json RELEASE.json credentials_included)" == false ]] || exit 3
bnn_archive="$(bnn_json RELEASE.json archive.name)"
[[ "$bnn_archive" =~ ^Hermes-BNN-[A-Za-z0-9._-]+\.tar\.gz$ ]] || exit 3
bnn_hash="$(bnn_json RELEASE.json archive.sha256)"
bnn_bytes="$(bnn_json RELEASE.json archive.bytes)"
[[ "$(bnn_json PARTS.json archive.sha256)" == "$bnn_hash" && "$(bnn_json PARTS.json archive.name)" == "$bnn_archive" && "$(bnn_json PARTS.json archive.bytes)" == "$bnn_bytes" ]] || exit 3
bnn_parts=(); bnn_index=0
while bnn_name="$(bnn_json PARTS.json "parts.$bnn_index.name")"; do
 [[ "$bnn_index" -lt 500 && "$bnn_name" == "$(printf '%s.part%03d' "$bnn_archive" "$((bnn_index+1))")" ]] || exit 3
 bnn_part_hash="$(bnn_json PARTS.json "parts.$bnn_index.sha256")"
 bnn_part_bytes="$(bnn_json PARTS.json "parts.$bnn_index.bytes")"
 [[ "$bnn_part_hash" =~ ^[a-f0-9]{64}$ && "$bnn_part_bytes" =~ ^[0-9]+$ ]] || exit 3
 if [[ -z "$bnn_metadata_only" ]]; then bnn_fetch "$bnn_name"; bnn_verify_file "$bnn_part_hash" "$bnn_name" "$bnn_part_bytes"; fi
 bnn_parts+=("$bnn_name"); bnn_index=$((bnn_index+1))
done
[[ "$bnn_index" -gt 0 ]] || exit 3
if [[ -n "$bnn_metadata_only" ]]; then echo 'Signatures and manifest sequence verified; archive parts were not downloaded.'; exit 0; fi
if [[ ! -e "$bnn_archive" ]]; then
 [[ ! -e "$bnn_archive.assembling" && ! -L "$bnn_archive.assembling" ]] || { echo 'Previous assembly exists; inspect it before retrying.' >&2; exit 3; }
 cat "${bnn_parts[@]}" > "$bnn_archive.assembling"
 bnn_verify_file "$bnn_hash" "$bnn_archive.assembling" "$bnn_bytes"
 mv "$bnn_archive.assembling" "$bnn_archive"
else bnn_verify_file "$bnn_hash" "$bnn_archive" "$bnn_bytes"; fi
echo 'Full archive verified. Extract into a new local folder; follow Hermes-BNN-Full/docs/INSTALL_MACOS.md. Existing owner data must not be overwritten.'
