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
- Top 5 processes by CPU time

All data is sent to your GreenSecOps instance only. Nothing is shared externally.
