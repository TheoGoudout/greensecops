# GreenSecOps Telemetry Action

Add this action to your workflow to enable dynamic analysis with runtime telemetry.

## Usage

This action authenticates with **GitHub OIDC** — no API token or secret is
required. Your job must grant `id-token: write` permission.

```yaml
jobs:
  build:
    permissions:
      id-token: write # required for GreenSecOps OIDC authentication
    steps:
      # ... your build steps ...
      - name: GreenSecOps Telemetry
        uses: theogoudout/greensecops@main
        with:
          greensecops_url: https://app.greensecops.com
          # sample_interval: "30"  # optional, seconds between samples
```

Add it as the **last step** in your job to capture accurate resource usage.

## Collected Data

- Runner specs: OS, arch, vCPUs, RAM, disk
- CPU usage % (sampled over 2 seconds)
- RAM usage (used MB, %)
- Disk usage
- Network I/O counters
- Top 5-10% resource-consuming processes by CPU/RAM (Linux runners only, via
  the bundled `proc-sampler` binary — silently omitted elsewhere)

All data is sent to your GreenSecOps instance only. Nothing is shared externally.

## Development

`dist/` is committed (this action ships without a consumer-side build step,
same as every other `uses:`-able action). `dist/bin/proc-sampler-linux-*` are
prebuilt Go binaries, not bundled by `ncc` — cross-compile them first, then
`bun run build` copies them in:

```bash
cd native/proc-sampler
CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build -o build/proc-sampler-linux-amd64 .
CGO_ENABLED=0 GOOS=linux GOARCH=arm64 go build -o build/proc-sampler-linux-arm64 .
CGO_ENABLED=0 GOOS=linux GOARCH=386   go build -o build/proc-sampler-linux-386 .
cd ../..
bun run build
```
