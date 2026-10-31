#!/bin/bash
set -euo pipefail
umask 077
bnn_destination="${1:?Usage: bash download.sh /new/download/folder}"
bnn_repository="${HERMES_BNN_REPOSITORY:-olegeklepikov-collab/hermes-bnn-full}"
bnn_tag='full-20261031-intake-0.14.3'
mkdir -p "$bnn_destination"
cd "$bnn_destination"
fetch() {
 local bnn_file="$1" bnn_sha="$2"
 if [[ -e "$bnn_file" ]]; then
  printf '%s  %s\n' "$bnn_sha" "$bnn_file" | shasum -a 256 -c -
  return
 fi
 if [[ "$bnn_repository" == *-private ]]; then
  command -v gh >/dev/null || { echo 'Private repository: authenticate gh, or download all release assets in your browser.' >&2; exit 3; }
  gh release download "$bnn_tag" --repo "$bnn_repository" --pattern "$bnn_file" --dir .
 else
  [[ ! -e "$bnn_file.downloading" ]] || { echo 'Partial download preserved; inspect it before retrying.' >&2; exit 4; }
  curl --fail --location --retry 2 --proto '=https' --tlsv1.2 --output "$bnn_file.downloading" "https://github.com/$bnn_repository/releases/download/$bnn_tag/$bnn_file"
  printf '%s  %s\n' "$bnn_sha" "$bnn_file.downloading" | shasum -a 256 -c -
  mv "$bnn_file.downloading" "$bnn_file"
 fi
 printf '%s  %s\n' "$bnn_sha" "$bnn_file" | shasum -a 256 -c -
}
fetch 'RELEASE.json' '813639d93026220f0e4b112207a3fd6cb65d586cb1e993d81589671d037ef52d'
fetch 'SHA256SUMS' 'd24dd7a9009926a617360ffffdbd2920fffba987f9b7cde7d56a28ab817ba2aa'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part001' '0063fd7f96a874825d137196d9e79888a97e890b51716f0bc194df0c68f533eb'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part002' '97bc085d5995ad5b7e0ba29cc9f1b23d35db5a8561f6270405ee8ca378aa2a11'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part003' 'dfb83b472cc256ae292f9e0f53a8fd111b0565968d812ad09e3865873f77fca5'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part004' '3cf4d1ccb91b86f19395060896c092fcd4cadca002ce3b9453bdcfdfd3095fa2'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part005' 'd4988caf5957a93fa2246b98fa1d0fe11a7e560420a50dd9ebb56480d27535fa'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part006' '449b4d2db8d0a8a44646b994640ba4242f11acc0bad8150da67126af39696a2d'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part007' 'c78e8ccea1f5be0ec9f101fb8e056f7c1f2e05bc029e1418707dc71b5b27e3f0'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part008' 'eaa3611f8e5c4c3d6c9c106dc3925e948f1bec62bbdc4254c0baded430a08633'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part009' 'f45cf0cfc7c608d1a572ab5604ed81445bf3e0d43a37de8454ade09ad6ac58fe'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part010' '1e47726f6a48d69e568a438c6c6bb9e15bcd318bd8186af72e5351b9656e5efc'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part011' '9f43c643451b5f754ff6d8f474d35065da7a8bfc70965eaac52fb871f376b838'
fetch 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part012' '418d5f0b05a0a74c3133b5e1db7216ff83d0fccf1f60f691748f142687f20007'
if [[ ! -e 'Hermes-BNN-Full.tar.gz' ]]; then
 [[ ! -e 'Hermes-BNN-Full.tar.gz.assembling' ]] || { echo "Incomplete assembly preserved" >&2; exit 5; }
 cat 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part001' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part002' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part003' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part004' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part005' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part006' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part007' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part008' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part009' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part010' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part011' 'Hermes-BNN-Full-20261031-Intake-0.14.3.tar.gz.part012' > 'Hermes-BNN-Full.tar.gz.assembling'
 printf '%s  %s\n' 'e1904902c82c59ea2c18802d8d9e420f59bbee68f548f3222da72a519d84ed97' 'Hermes-BNN-Full.tar.gz.assembling' | shasum -a 256 -c -
 mv 'Hermes-BNN-Full.tar.gz.assembling' 'Hermes-BNN-Full.tar.gz'
fi
shasum -a 256 -c SHA256SUMS
echo "Full archive verified. Read docs/INSTALL_MACOS.md before installation."
