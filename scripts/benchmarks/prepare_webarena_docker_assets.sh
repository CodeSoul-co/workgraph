#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ASSET_DIR="$ROOT_DIR/external/tools/webarena-docker/assets"
MIN_FREE_GIB="${MIN_FREE_GIB:-250}"
DOWNLOAD="${DOWNLOAD:-0}"

mkdir -p "$ASSET_DIR"

cat > "$ASSET_DIR/README.md" <<'EOF'
# WebArena Docker Assets

This directory is ignored by git. It is for the large official WebArena website
assets only. The official docs recommend an AMI or a large host; local full
deployment can require hundreds of GB.

Required official assets:

- shopping_final_0712.tar
- shopping_admin_final_0719.tar
- postmill-populated-exposed-withimg.tar
- gitlab-populated-final-port8023.tar
- wikipedia_en_all_maxi_2022-05.zim

Run `DOWNLOAD=1 scripts/benchmarks/prepare_webarena_docker_assets.sh` only on a
machine with enough disk and network budget.
EOF

free_kib="$(df -k "$ROOT_DIR" | awk 'NR==2 {print $4}')"
free_gib="$((free_kib / 1024 / 1024))"
echo "free disk: ${free_gib}GiB; required threshold: ${MIN_FREE_GIB}GiB"

if [[ "$DOWNLOAD" != "1" ]]; then
  echo "DOWNLOAD=1 not set; wrote asset README only."
  exit 0
fi

if (( free_gib < MIN_FREE_GIB )); then
  echo "Not enough free disk for a safe WebArena full-site asset download." >&2
  echo "Set MIN_FREE_GIB lower only if you intentionally accept the risk." >&2
  exit 1
fi

cd "$ASSET_DIR"
curl -L --fail --continue-at - -o shopping_final_0712.tar \
  "https://archive.org/download/webarena-env-shopping-image/shopping_final_0712.tar"
curl -L --fail --continue-at - -o shopping_admin_final_0719.tar \
  "https://archive.org/download/webarena-env-shopping-admin-image/shopping_admin_final_0719.tar"
curl -L --fail --continue-at - -o postmill-populated-exposed-withimg.tar \
  "https://archive.org/download/webarena-env-forum-image/postmill-populated-exposed-withimg.tar"
curl -L --fail --continue-at - -o gitlab-populated-final-port8023.tar \
  "https://archive.org/download/webarena-env-gitlab-image/gitlab-populated-final-port8023.tar"
curl -L --fail --continue-at - -o wikipedia_en_all_maxi_2022-05.zim \
  "https://archive.org/download/webarena-env-wiki-image/wikipedia_en_all_maxi_2022-05.zim"

echo "Downloaded WebArena official assets to $ASSET_DIR"
