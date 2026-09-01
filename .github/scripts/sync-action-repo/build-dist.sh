#!/usr/bin/env bash
# Build the action's dist/ in the public repo and commit it there.
#
# GH_TOKEN, TARGET and SHA come from the calling step's env.
set -euo pipefail

rm -rf /tmp/public-action
git clone "https://x-access-token:${GH_TOKEN}@github.com/${TARGET}.git" /tmp/public-action
cd /tmp/public-action
git config user.name "greensecops-bot"
git config user.email "bot@greensecops.com"

# dist/bin/* aren't bundled by ncc — cross-compile them first so the build step
# below has something to copy in.
mkdir -p native/proc-sampler/build
for arch in 386 amd64 arm64; do
  (cd native/proc-sampler && CGO_ENABLED=0 GOOS=linux GOARCH="${arch}" \
    go build -o "build/proc-sampler-linux-${arch}" .)
done

bun install
bun run build
git add -f dist
if git diff --cached --quiet; then
  echo "changed=false" >> "$GITHUB_OUTPUT"
else
  git commit -m "chore: rebuild dist for ${SHA}"
  git push origin main
  echo "changed=true" >> "$GITHUB_OUTPUT"
fi
