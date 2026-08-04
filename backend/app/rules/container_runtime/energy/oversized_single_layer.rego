# METADATA
# title: One layer dominates the image
# description: Measured layer sizes show a single layer accounting for most of the image. The whole-image oversized_image check says the result is big; this says where. A layer that large is almost always one RUN that installs, builds and cleans up in separate commands, or a COPY that brought in a directory nobody meant to ship — and because it is one layer, any change to it re-pushes and re-pulls the entire thing.
# custom:
#   severity: medium
#   detection: dynamic_analysis
#   examples:
#     bad: |
#       build:
#         image_size_bytes: 900000000
#         layers: [{"index": 0, "size_bytes": 780000000, "instruction": "RUN"}]
#     good: |
#       build:
#         image_size_bytes: 240000000
#         layers: [{"index": 0, "size_bytes": 60000000, "instruction": "RUN"}]
#     fix: |
#       Find the instruction at that layer index and split it. Package installs and their cleanup must be in the same RUN to actually shrink the layer, while unrelated steps belong in their own so a change to one does not invalidate the rest. If it is a COPY, add a .dockerignore.
package greensecops.container_runtime.energy.oversized_single_layer

import rego.v1

# Below this, "one big layer" is just a small image with few layers.
_min_layer_bytes := 300000000

_dominant_share := 0.5

violations contains violation if {
	some layer in input.build.layers
	size := layer.size_bytes
	is_number(size)
	size > _min_layer_bytes

	total := input.build.image_size_bytes
	is_number(total)
	total > 0
	size >= total * _dominant_share

	violation := {
		"rule": "oversized_single_layer",
		"severity": "medium",
		"category": "energy",
		"evidence": sprintf("layer %v (%v) is %v MB of a %v MB image", [layer.index, object.get(layer, "instruction", "?"), round(size / 1000000), round(total / 1000000)]),
		"recommendation": sprintf("Split the %v at layer %v — combine its install and cleanup into one command, and move unrelated work into its own layer so a change to one does not re-push all of it.", [object.get(layer, "instruction", "instruction"), layer.index]),
	}
}
