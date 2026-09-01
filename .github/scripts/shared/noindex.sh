#!/usr/bin/env bash
# Keep a built site out of search results.
#
#   noindex.sh <dist-dir>
#
# Staging and previews serve the same copy as production. Left alone they would
# be indexed and compete with it — there is no robots.txt in the repository, so
# nothing else prevents that. Both mechanisms are written because they catch
# different crawlers: robots.txt stops the ones that check before fetching,
# X-Robots-Tag stops the ones that do not check at all.
set -euo pipefail

if [ "$#" -ne 1 ]; then
  echo "usage: $0 <dist-dir>" >&2
  exit 2
fi

dist=$1

printf '\n/*\n  X-Robots-Tag: noindex, nofollow\n' >> "${dist}/_headers"
printf 'User-agent: *\nDisallow: /\n' > "${dist}/robots.txt"
