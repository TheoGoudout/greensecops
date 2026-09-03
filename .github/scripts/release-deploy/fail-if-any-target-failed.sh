#!/usr/bin/env bash
# Make the run's conclusion the release's conclusion.
#
# report.sh above writes the table and always exits 0, which is right for a
# report and wrong for the last job in the workflow: the summary job ran
# `if: always()`, so a release whose Cloudflare deploy died still ended on a
# green check. The failure was in the table nobody clicks into.
#
# Skipped is not failed — a `targets: cloudflare` dispatch deliberately skips
# the API half, and that run should be able to go green.
#
# IMAGES, API and STATIC come from the calling step's env.
set -euo pipefail

failed=""
for stage in "Images:${IMAGES}" "API:${API}" "Static surfaces:${STATIC}"; do
  name=${stage%%:*}
  result=${stage#*:}
  case "${result}" in
    failure | cancelled) failed="${failed} ${name}(${result})" ;;
  esac
done

if [ -n "${failed}" ]; then
  echo "::error::Release stage(s) did not complete:${failed}. Re-run the failed" \
       "jobs, or re-drive one half with the workflow_dispatch 'targets' input."
  exit 1
fi
