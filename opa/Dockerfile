# Pinned by digest rather than by tag alone so policy evaluation is
# reproducible across builds. The -static variant is multi-arch
# (amd64 + arm64) — required because the deployment host is arm64. Rules use
# `import rego.v1`, the default dialect since OPA 1.0.
FROM openpolicyagent/opa:1.18.2-static@sha256:57f7d06808fff6de3ea1d698e6430990973ca1370be0e54975f0083d615521da

LABEL org.opencontainers.image.source="https://github.com/TheoGoudout/greensecops"
LABEL org.opencontainers.image.licenses="MIT"

COPY backend/app/rules /policies

# Numeric rather than a name: the base image is distroless, so there is no
# guarantee a named account resolves. 65532 is the conventional distroless
# `nonroot` uid. OPA serves on 8181 (unprivileged) and only ever reads
# /policies, so it needs nothing root grants.
USER 65532:65532
