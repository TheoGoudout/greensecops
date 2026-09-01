#!/usr/bin/env bash
# Block until this commit's images.yml run — which ends in the staging API
# deploy — has finished successfully.
#
# The dashboard ships a *generated* OpenAPI client, so publishing it before the
# API that serves that contract is the one mismatch direction that actually
# breaks: a client calling endpoints the server has not shipped.
# release-deploy.yml sequences production for exactly this reason; this is
# staging's equivalent.
#
# The API deploy is the last job of images.yml, so waiting for that run to finish
# is waiting for the API. A commit that changed nothing images.yml watches has no
# run at all, and publishes immediately.
#
# GH_TOKEN, REPO and SHA come from the calling step's env.
set -euo pipefail

status=""; conclusion=""; url=""

# Sets the three above from the newest images.yml run for this commit, and
# returns non-zero if the API could not be read. That distinction matters: a
# failed call must not be mistaken for "no run exists", which would publish the
# dashboard on an API error.
#
# Pipe-separated rather than space-separated, because `read` with the default IFS
# collapses runs of whitespace — an in-progress run, whose conclusion is empty,
# would shift its URL into the conclusion field and be read as a failure.
# `.workflow_runs // []` keeps a malformed response an empty list rather than a
# jq error.
poll() {
  local out
  if ! out=$(gh api "repos/${REPO}/actions/runs?head_sha=${SHA}&per_page=100" \
    --jq '(.workflow_runs // [])
          | map(select(.path == ".github/workflows/images.yml"))
          | sort_by(.run_started_at)
          | last
          | "\(.status // "")|\(.conclusion // "")|\(.html_url // "")"' 2>&1); then
    echo "  Could not list this commit's runs: ${out}"
    return 1
  fi
  IFS='|' read -r status conclusion url <<< "${out}"
}

# No run is ambiguous for a short window: a workflow filtered out by its `paths:`
# produces no run at all, which looks exactly like one that has not been created
# yet. Both this workflow and images.yml are started by the same push, so give
# the latter a grace period to appear before concluding it never will.
read_once=false
for attempt in $(seq 1 9); do
  if poll; then
    read_once=true
    if [ -n "${status}" ]; then
      break
    fi
    echo "  No images run for ${SHA} yet (${attempt}/9)."
  fi
  sleep 10
done

# An API that never answered is not the same as a commit with no run, and
# concluding the latter from the former would publish the dashboard on an
# outage. Only silence that was actually *read* counts as absence.
if [ "${read_once}" != "true" ]; then
  echo "::error::Could not read this commit's workflow runs at all, so whether the staging API deployed is unknown. Refusing to publish the dashboard."
  exit 1
fi

if [ -z "${status}" ]; then
  echo "::notice::No images.yml run for ${SHA} — the API is unchanged by this commit, so there is nothing to wait for."
  exit 0
fi

echo "Waiting on ${url}"

# 120 x 20s = 40 minutes, which covers four image builds, two manifest merges and
# a Coolify rollout with room to spare. Capped rather than left to the job
# timeout so the failure names the run. A read that fails is retried rather than
# fatal — the run is very likely still going, and the cap is what stops this
# waiting forever.
for attempt in $(seq 1 120); do
  if [ "${status}" = "completed" ]; then
    break
  fi
  echo "  ${status} (${attempt}/120)"
  sleep 20
  poll || true
done

if [ "${status}" != "completed" ]; then
  echo "::error::${url} was still '${status}' after 40 minutes. The dashboard has NOT been published — it would have gone out ahead of the API."
  exit 1
fi

if [ "${conclusion}" != "success" ]; then
  echo "::error::${url} finished '${conclusion}', so the staging API is not on ${SHA}. Refusing to publish a dashboard ahead of it — fix that run, then re-run this one."
  exit 1
fi

echo "Staging API is on ${SHA} ✅"
