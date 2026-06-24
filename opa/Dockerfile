FROM alpine:3.22 AS wget-builder
RUN apk add --no-cache wget

FROM openpolicyagent/opa:latest
COPY --from=wget-builder /usr/bin/wget /usr/bin/wget
COPY backend/app/rules /policies
