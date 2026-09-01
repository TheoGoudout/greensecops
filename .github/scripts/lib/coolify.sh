# shellcheck shell=bash
#
# The Coolify API, as the three callers that talk to it need it.
#
# Sourced, never executed — no shebang, no executable bit. Callers:
#   .github/scripts/images/coolify-deploy.sh          staging
#   .github/scripts/images/coolify-monitor.sh         staging
#   .github/scripts/release-deploy/coolify-deploy.sh  production
#   .github/scripts/release-deploy/coolify-monitor.sh production
#   .github/scripts/shared/coolify-env-sync.sh        both
#
# Every one of them had its own copy of `call` and `require_ok` before the
# workflows' shell moved out of the YAML, which is precisely how the copies got
# there: three near-identical programs in three files nothing linted and nothing
# diffed. The differences that remain between staging and production are real
# and live in the callers — production repoints the resource's git ref at the
# release tag, staging tracks `main` permanently and must not.
#
# COOLIFY_URL and COOLIFY_TOKEN are read from the environment.

# Set by coolify_call, read by everything after it.
coolify_status=""
coolify_body=""

# Fail unless every named variable is set and non-empty.
#
#   coolify_require_env COOLIFY_URL COOLIFY_TOKEN UUID
#
# A missing secret would otherwise reach the API as /applications//envs and come
# back as an unhelpful 404 rather than as the missing secret it is.
coolify_require_env() {
  local name missing=0
  for name in "$@"; do
    if [ -z "${!name:-}" ]; then
      echo "::error::The ${name} secret is not set." >&2
      missing=1
    fi
  done
  return "${missing}"
}

# Call the API, setting coolify_status and coolify_body.
#
#   coolify_call METHOD PATH [extra curl arguments...]
#
# Call it directly — never inside $( ), which would run it in a subshell and
# discard both assignments.
#
# Not `curl -f`: that throws away the response body on an error status, which is
# the half of a 4xx that says *why*. Losing it turned the first real release
# failure into a bare "curl: (22) 404" with nothing to act on.
coolify_call() {
  local method=$1 path=$2
  shift 2
  local response
  response=$(curl -sS --max-time 60 -w '\n%{http_code}' -X "${method}" \
    -H "Authorization: Bearer ${COOLIFY_TOKEN}" \
    -H "Content-Type: application/json" \
    "${COOLIFY_URL}/api/v1${path}" "$@")
  coolify_status=${response##*$'\n'}
  coolify_body=${response%$'\n'*}
}

# Exit unless the last coolify_call succeeded. The argument names the operation,
# so the error says which one failed.
coolify_require_ok() {
  if [ "${coolify_status}" -lt 200 ] || [ "${coolify_status}" -ge 300 ]; then
    echo "::error::$1 failed with HTTP ${coolify_status}: ${coolify_body}" >&2
    exit 1
  fi
}

# Set one environment variable on a resource, creating it if it is not there.
#
#   coolify_upsert_env UUID KEY VALUE
#
# Upsert, because PATCH and POST are not interchangeable here: PATCH updates an
# existing variable and 404s when there is none; POST creates one. Which applies
# depends on whether the variable was ever set on this resource by hand — not
# something a deploy should have an opinion about. The first production release
# failed exactly here, 404ing on a resource where TAG had never been created.
coolify_upsert_env() {
  local app_uuid=$1 key=$2 value=$3 payload
  payload=$(jq -nc --arg k "${key}" --arg v "${value}" '{key: $k, value: $v}')

  coolify_call PATCH "/applications/${app_uuid}/envs" -d "${payload}"
  if [ "${coolify_status}" = "404" ]; then
    echo "  No ${key} variable on this resource yet — creating it."
    coolify_call POST "/applications/${app_uuid}/envs" -d "${payload}"
    coolify_require_ok "Creating the ${key} variable"
  else
    coolify_require_ok "Setting the ${key} variable"
  fi
}

# Queue a deploy and echo its deployment uuid, so it can be monitored.
#
#   deployment=$(coolify_trigger_deploy "${UUID}")
coolify_trigger_deploy() {
  local app_uuid=$1 deploy_id
  coolify_call POST "/deploy?uuid=${app_uuid}&force=true"
  coolify_require_ok "Triggering the deploy"
  deploy_id=$(jq -r '.deployments[0].deployment_uuid // empty' <<< "${coolify_body}")

  if [ -z "${deploy_id}" ]; then
    echo "::error::Coolify accepted the deploy request but returned no deployment_uuid, so it cannot be monitored." >&2
    exit 1
  fi
  echo "${deploy_id}"
}

# Poll a deployment to its conclusion; exit 0 on success, 1 on anything else.
#
#   coolify_monitor_deploy DEPLOYMENT LABEL TAG
#
# LABEL names the deployment in the run summary — "Staging API deploy",
# "Coolify deploy".
#
# Coolify's queue has a documented long tail of deployments that sit in queued
# or in_progress indefinitely, so this caps the wait rather than leaning on the
# job timeout — a capped failure names the deployment and prints its log, a job
# timeout does neither.
coolify_monitor_deploy() {
  local deploy_id=$1 label=$2 tag=$3
  local status="unknown" attempt http

  for attempt in $(seq 1 90); do
    # Keep the body on an error status so a failure here says what Coolify
    # actually returned rather than just a curl exit code. A transient 5xx
    # mid-rollout is not fatal — retry it rather than abandoning a deploy that
    # is very likely still progressing.
    local response
    response=$(curl -sS --max-time 30 -w '\n%{http_code}' \
      -H "Authorization: Bearer ${COOLIFY_TOKEN}" \
      "${COOLIFY_URL}/api/v1/deployments/${deploy_id}")
    http=${response##*$'\n'}
    coolify_body=${response%$'\n'*}

    if [ "${http}" -lt 200 ] || [ "${http}" -ge 300 ]; then
      echo "  HTTP ${http} polling the deployment (${attempt}/90): ${coolify_body}"
      sleep 10
      continue
    fi

    status=$(jq -r '.status // "unknown"' <<< "${coolify_body}")

    case "${status}" in
      finished)
        return 0
        ;;
      failed|cancelled-by-user)
        echo "::error::Coolify reported '${status}' for deployment ${deploy_id}."
        {
          echo "## ${label} ${status}"
          echo
          echo "Deployment \`${deploy_id}\` for \`${tag}\`."
          jq -r '.deployment_url // empty' <<< "${coolify_body}" | sed 's/^/Logs: /'
          echo
          echo '```'
          jq -r '.logs // "(no logs returned)"' <<< "${coolify_body}" | tail -100
          echo '```'
        } >> "$GITHUB_STEP_SUMMARY"
        return 1
        ;;
      queued|in_progress)
        echo "  ${status} (${attempt}/90)"
        ;;
      *)
        echo "  unrecognised status '${status}' (${attempt}/90)"
        ;;
    esac
    sleep 10
  done

  echo "::error::Deployment ${deploy_id} was still '${status}' after 15 minutes."
  return 2
}
