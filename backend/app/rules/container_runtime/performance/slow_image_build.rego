# METADATA
# title: Image build took a long time
# description: Measured build duration shows the image took several minutes to build. Unlike the layer-cache check, which needs several builds before it can say the cache is not being reused, this fires on a single observation — a long build is paid on every push by every contributor, and it is the part of CI latency that compounds, because nothing downstream can start until the image exists.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       build: {"build_duration_ms": 900000}
#     good: |
#       build: {"build_duration_ms": 95000}
#     fix: |
#       Look at what is being rebuilt rather than reused. The usual causes are a COPY of the whole source tree before the dependency install (so any commit invalidates it), a missing registry cache between CI runs, and compiling a dependency from source that has a wheel or prebuilt binary available.
package greensecops.container_runtime.performance.slow_image_build

import rego.v1

# Five minutes. Long enough that a well-cached build of a large image is not
# flagged, short enough to catch a build that rebuilds the world every time.
_slow_build_ms := 300000

violations contains violation if {
	duration := input.build.build_duration_ms
	is_number(duration)
	duration > _slow_build_ms

	violation := {
		"rule": "slow_image_build",
		"severity": "medium",
		"category": "performance",
		"evidence": sprintf("image build took %v minutes", [round((duration * 10) / 60000) / 10]),
		"recommendation": "Copy dependency manifests and install them before copying the source, so a code change does not invalidate the dependency layer, and persist a registry cache between CI runs.",
	}
}
