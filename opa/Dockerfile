# Pinned rather than :latest so policy evaluation is reproducible across
# builds. The -static variant is multi-arch (amd64 + arm64) — required
# because the deployment host is arm64. Rules use `import rego.v1`,
# the default dialect since OPA 1.0.
FROM openpolicyagent/opa:1.18.2-static
COPY backend/app/rules /policies
