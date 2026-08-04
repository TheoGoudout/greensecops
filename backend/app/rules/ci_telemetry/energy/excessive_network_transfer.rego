# METADATA
# title: Run transferred a large amount of data over the network
# description: Measured network counters show the runner moved several gigabytes during the job. On a fresh runner almost all inbound traffic is downloads — base images, packages, toolchains — so a large figure usually means something is being fetched every run that a cache would have supplied. Unlike the static caching_missing check, which infers the problem from the workflow's shape, this measures what actually crossed the wire.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       metrics: {"net_bytes_recv": 9000000000, "net_bytes_sent": 200000000}
#     good: |
#       metrics: {"net_bytes_recv": 700000000, "net_bytes_sent": 90000000}
#     fix: |
#       Find what is downloaded on every run and cache it — dependency trees, Docker base layers and toolchain installs are the usual three. A registry cache for image layers and a lockfile-keyed dependency cache between runs remove most of it.
package greensecops.ci_telemetry.energy.excessive_network_transfer

import rego.v1

# 5 GB. A job that pulls a base image and a dependency tree from cold sits
# well under this; several gigabytes means it is doing so repeatedly.
_large_transfer_bytes := 5000000000

_total_bytes := sent + received if {
	sent := object.get(input.metrics, "net_bytes_sent", 0)
	received := object.get(input.metrics, "net_bytes_recv", 0)
	is_number(sent)
	is_number(received)
}

violations contains violation if {
	total := _total_bytes
	total > _large_transfer_bytes

	violation := {
		"rule": "excessive_network_transfer",
		"severity": "medium",
		"category": "energy",
		"evidence": sprintf("the run transferred %v MB over the network", [round(total / 1000000)]),
		"recommendation": "Cache what is being downloaded on every run — dependency trees, image layers and toolchain installs. Measured transfer this high usually means a cache is missing rather than that the job genuinely needs the data.",
	}
}
