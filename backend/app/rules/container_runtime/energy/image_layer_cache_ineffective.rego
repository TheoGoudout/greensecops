# METADATA
# title: Image layer cache is not being reused
# description: Measured build telemetry shows most layers rebuilding rather than hitting the cache. This is the measured counterpart to the static copy_before_dependency_install check — that rule infers a cache problem from instruction order, this one observes that the cache is actually missing, whatever the cause.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       cache_hit_ratio: 0.18
#       build_duration_ms: 260000
#     good: |
#       cache_hit_ratio: 0.86
#       build_duration_ms: 24000
#     fix: |
#       Copy dependency manifests and install them before copying the rest of the source, so the install layer survives a source edit. In CI, the cache also has to persist between runs — a runner with no registry or BuildKit cache mount starts cold every time however well the Dockerfile is ordered.
package greensecops.container_runtime.energy.image_layer_cache_ineffective

import rego.v1

_low_hit_ratio := 0.4

# Cache-hit ratio only means something once a build has repeated: the first
# build of any image legitimately misses every layer.
_min_builds := 3

violations contains violation if {
	ratio := input.build.cache_hit_ratio
	builds := object.get(input.build, "observed_builds", 0)
	builds >= _min_builds
	ratio < _low_hit_ratio
	violation := {
		"rule": "image_layer_cache_ineffective",
		"severity": "medium",
		"category": "energy",
		"evidence": sprintf("cache hit ratio %.0f%% across %v builds", [ratio * 100, builds]),
		"recommendation": "Copy dependency manifests and install before copying source, and make sure the layer cache persists between CI runs.",
	}
}
