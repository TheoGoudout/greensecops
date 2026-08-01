# A correct multi-stage Node build: the toolchain stays in the builder, the
# manifests are copied before the install so the dependency layer is cached,
# and only the built artifact reaches the shipped stage.
FROM node:22-slim@sha256:2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a AS builder

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM node:22-slim@sha256:2b3c4d5e6f708192a3b4c5d6e7f8091a2b3c4d5e6f708192a3b4c5d6e7f8091a

LABEL org.opencontainers.image.source="https://github.com/TheoGoudout/greensecops"

WORKDIR /app
COPY --from=builder /app/dist ./dist
COPY --from=builder /app/node_modules ./node_modules

USER node

HEALTHCHECK --interval=30s --timeout=3s CMD node dist/healthcheck.js

CMD ["node", "dist/server.js"]
