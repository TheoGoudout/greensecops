# METADATA
# title: Image has a very large number of layers
# description: Measured layer data shows the image is built from far more layers than a typical service image needs. Each layer is a separate tarball to store, transfer and unpack, and every consecutive RUN adds one — so a Dockerfile written as a long list of single commands pays for that shape on every pull, on every runner, forever. Layer count also has a hard ceiling in the storage driver, which a generated Dockerfile can reach.
# custom:
#   severity: low
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       build:
#         layers: [{"index": 0, "size_bytes": 100, "instruction": "RUN"}]  # ...and 60 more
#     good: |
#       build:
#         layers: [{"index": 0, "size_bytes": 100, "instruction": "RUN"}]  # ...and 12 more
#     fix: |
#       Merge consecutive RUN instructions that belong to one step, joining them with && so they share a layer. Keep the split where it buys cache reuse — dependency installation should stay in its own layer, separate from the source copy that changes every commit.
package greensecops.container_runtime.energy.excessive_layer_count

import rego.v1

# A multi-stage service image lands around 15-25 layers. Fifty is a Dockerfile
# written one command per line.
_layer_count_threshold := 50

violations contains violation if {
	layers := input.build.layers
	is_array(layers)
	count(layers) > _layer_count_threshold

	violation := {
		"rule": "excessive_layer_count",
		"severity": "low",
		"category": "energy",
		"evidence": sprintf("image is built from %v layers", [count(layers)]),
		"recommendation": "Merge consecutive RUN instructions that form one logical step, keeping dependency installation in its own layer so it still caches independently of the source copy.",
	}
}
