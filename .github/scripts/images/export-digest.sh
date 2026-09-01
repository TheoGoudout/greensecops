#!/usr/bin/env bash
# Record one architecture's image digest as an artifact file.
#
# The artifact is an empty file whose *name* is the digest; the merge job reads
# the names and ignores the contents.
#
# The `sha256:` prefix has to come off. upload-artifact rejects a colon anywhere
# in a path — it keeps artifacts extractable on NTFS, where the character is
# illegal — and the merge job re-adds the prefix when it rebuilds the full
# references, so leaving it here would produce `image@sha256:sha256:…` even if
# the upload had succeeded.
#
# DIGEST comes from the build step's output, via the calling step's env.
set -euo pipefail

mkdir -p /tmp/digests
touch "/tmp/digests/${DIGEST#sha256:}"
