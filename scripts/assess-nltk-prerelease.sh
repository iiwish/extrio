#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:?receipt directory required}"
mkdir -p "$OUT/source"
OUT="$(cd "$OUT" && pwd)"
COMMIT=ba6b259aa94a85168c031ad60e4072538c30b513
SHA=2d401f212e7d872d9349bd43dedcab08bda54a807ce99957569725b567714464
curl --fail --location --silent --show-error "https://api.github.com/repos/nltk/nltk/tarball/$COMMIT" -o "$OUT/source.tar.gz"
printf '%s  %s\n' "$SHA" "$OUT/source.tar.gz" | sha256sum -c -
python3 -c 'import sys,tarfile; tarfile.open(sys.argv[1]).extractall(sys.argv[2],filter="data")' "$OUT/source.tar.gz" "$OUT/source"
SOURCE="$OUT/source/nltk-nltk-ba6b259"
test -f "$SOURCE/nltk/VERSION"
docker run --rm --network none --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 1g --cpus 2 --pids-limit 256 \
  --tmpfs /tmp:rw,mode=1777,size=128m \
  --tmpfs /home/extrio:rw,mode=0700,uid=10001,gid=10001,size=128m \
  --mount "type=bind,source=$SOURCE,target=/nltk-source,readonly" \
  --mount "type=bind,source=$ROOT/scripts/nltk-prerelease-probe.py,target=/probe.py,readonly" \
  -e HOME=/home/extrio -e EXTRIO_NLTK_ASSESSMENT=1 --entrypoint /opt/extrio/bin/python extrio/backend:slim-noble \
  /probe.py > "$OUT/assessment.json"
