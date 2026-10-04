#!/usr/bin/env bash
# Refuse to run without the PAT the bump commit has to be pushed with.
#
# GITHUB_TOKEN pushes do not trigger other workflows, so a bump commit pushed
# with it lands on the default branch with no CI at all — and the release would then be cut
# from a commit nothing ever checked.
set -euo pipefail

echo "::error::RELEASE_TOKEN is not configured. Without it the bump commit is" \
  "pushed with GITHUB_TOKEN and no CI runs against the released code."
exit 1
