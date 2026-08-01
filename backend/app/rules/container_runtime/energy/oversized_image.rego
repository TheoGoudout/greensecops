# METADATA
# title: Published image is very large
# description: Measured image size is above the threshold where pull time and registry storage start to dominate. Unlike the static no_multistage_build and heavy_base_image checks, which infer bloat from the Dockerfile's shape, this is the shipped artifact's actual size.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       image_size_bytes: 2400000000
#     good: |
#       image_size_bytes: 180000000
#     fix: |
#       Move the build into a builder stage and COPY only the artifact into a clean final stage, then check the per-layer sizes to find what is actually large — it is usually a package cache, a node_modules tree that was never pruned, or build tooling that never needed to ship.
package greensecops.container_runtime.energy.oversized_image

import rego.v1

_large_image_bytes := 1000000000

violations contains violation if {
	size := input.build.image_size_bytes
	size > _large_image_bytes
	violation := {
		"rule": "oversized_image",
		"severity": "medium",
		"category": "energy",
		"evidence": sprintf("final image is %.1f GB", [size / 1000000000]),
		"recommendation": "Split the build into stages and ship only the artifact; check per-layer sizes to find what is large.",
	}
}
