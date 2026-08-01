# METADATA
# title: Build context is far larger than the image
# description: The context uploaded to the builder dwarfs the image it produces, which almost always means a missing or incomplete .dockerignore — the whole working tree, including .git, node_modules and build output, is being sent to the daemon on every build. Static analysis cannot see this at all, because the context's contents are not described anywhere in the Dockerfile.
# custom:
#   severity: low
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       context_size_bytes: 900000000
#       image_size_bytes: 90000000
#     good: |
#       context_size_bytes: 12000000
#       image_size_bytes: 90000000
#     fix: |
#       Add a .dockerignore covering .git, node_modules, build output, local virtualenvs and test fixtures. The context is transferred on every build, so this is paid on each one, not once.
package greensecops.container_runtime.energy.bloated_build_context

import rego.v1

_context_ratio_threshold := 2.0

_min_context_bytes := 100000000

violations contains violation if {
	context_size := input.build.context_size_bytes
	image_size := input.build.image_size_bytes
	image_size > 0

	# A tiny project can exceed the ratio harmlessly; the absolute floor keeps
	# this to contexts that actually cost transfer time.
	context_size > _min_context_bytes
	ratio := context_size / image_size
	ratio > _context_ratio_threshold
	violation := {
		"rule": "bloated_build_context",
		"severity": "low",
		"category": "energy",
		"evidence": sprintf("context %.0f MB vs image %.0f MB (%.1fx)", [context_size / 1000000, image_size / 1000000, ratio]),
		"recommendation": "Add or extend .dockerignore — the context is uploaded on every build.",
	}
}
