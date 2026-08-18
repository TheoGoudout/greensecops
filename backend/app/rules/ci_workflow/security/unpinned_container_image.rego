# METADATA
# title: Unpinned container image in a job
# description: "A job container: or services: entry names an image by tag, or by no tag at all. Tags move — an image pulled today is not the image pulled last week — so the job's build environment or its database changes without any commit, and a compromised upstream tag lands straight in a job holding the workflow's token. This is the same discipline already applied to actions, on the other half of what a job actually runs."
# custom:
#   severity: medium
#   severity_weight: 1.2
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           container: node:20
#           services:
#             postgres:
#               image: postgres:16
#           steps:
#             - run: npm test
#     good: |
#       jobs:
#         test:
#           runs-on: ubuntu-latest
#           container: node:20@sha256:bb63b5b0d0f9a0b0c0d0e0f00102030405060708090a0b0c0d0e0f1011121314
#           services:
#             postgres:
#               image: postgres:16@sha256:0102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f20
#           steps:
#             - run: npm test
#     fix: |
#       Append the image digest — image:tag@sha256:... — keeping the tag as the human-readable half exactly as an action pin keeps its version comment. Dependabot updates digests in the docker ecosystem, so pinning does not mean going stale.
package greensecops.ci_workflow.security.unpinned_container_image

import rego.v1

_is_digest_pinned(image) if {
	is_string(image)
	contains(image, "@sha256:")
}

# `container:` accepts either a bare string or a mapping with an `image:` key.
_container_image(job) := job.container if is_string(job.container)

_container_image(job) := job.container.image if {
	is_object(job.container)
	is_string(job.container.image)
}

violations contains violation if {
	some job_name, job in input.jobs
	image := _container_image(job)
	not _is_digest_pinned(image)

	violation := {
		"rule": "unpinned_container_image",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"message": sprintf("Job '%v' runs in container '%v', which is not pinned to a digest. The tag can move to a different image without any change here.", [job_name, image]),
		"context": image,
		"discriminator": sprintf("%v:container", [job_name]),
	}
}

violations contains violation if {
	some job_name, job in input.jobs
	some service_name, service in job.services
	image := _service_image(service)
	not _is_digest_pinned(image)

	violation := {
		"rule": "unpinned_container_image",
		"severity": "medium",
		"category": "security",
		"job": job_name,
		"message": sprintf("Service '%v' in job '%v' uses image '%v', which is not pinned to a digest. The tag can move to a different image without any change here.", [service_name, job_name, image]),
		"context": image,
		"discriminator": sprintf("%v:service:%v", [job_name, service_name]),
	}
}

_service_image(service) := service if is_string(service)

_service_image(service) := service.image if {
	is_object(service)
	is_string(service.image)
}
