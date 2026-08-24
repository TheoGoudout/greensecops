# METADATA
# title: Retired runner image requested
# description: A job asks for a runner image GitHub has retired. A retired label does not fail — it is silently migrated to a newer image, or the job simply never gets a runner, and which of those happens changes over time. Either way the workflow no longer says what it runs on, and a build that was pinned to an old image for a reason has quietly lost that pin without anything reporting it.
# custom:
#   severity: medium
#   detection: pattern_matching
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-20.04
#           steps:
#             - run: make build
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-24.04
#           steps:
#             - run: make build
#     fix: |
#       Move to a supported image. Prefer a pinned version (ubuntu-24.04) over the moving ubuntu-latest where the build depends on what is installed, since -latest changes underneath you on GitHub's own schedule.
package greensecops.ci_workflow.maintainability.deprecated_runner_image

import data.greensecops.lib.workflow as wf
import rego.v1

# Images GitHub has retired or announced for retirement. Bare labels only:
# a self-hosted runner whose label happens to contain one of these is matched
# on the exact label, not a substring.
_retired_images := {
	"macos-10.15",
	"macos-11",
	"macos-12",
	"macos-13",
	"ubuntu-16.04",
	"ubuntu-18.04",
	"ubuntu-20.04",
	"windows-2016",
	"windows-2019",
}

violations contains violation if {
	some job_name, job in input.jobs
	some label in wf.runs_on_labels(job)
	label in _retired_images

	violation := {
		"rule": "deprecated_runner_image",
		"severity": "medium",
		"category": "maintainability",
		"job": job_name,
		"message": sprintf("Job '%v' requests the retired runner image '%v'. A retired label is silently migrated or never scheduled, so the workflow no longer states what it runs on.", [job_name, label]),
		"context": label,
		"discriminator": sprintf("%v:%v", [job_name, label]),
	}
}
