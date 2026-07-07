# Pinned rather than :latest so policy evaluation is reproducible across
# builds. Rules use `import rego.v1`, supported since OPA 0.59.
FROM openpolicyagent/opa:0.70.0
COPY backend/app/rules /policies
