# METADATA
# title: Galaxy dependency with no version
# description: A collection or role in requirements.yml with no version installs whatever Galaxy currently serves, so two runs a week apart can install different code and a broken upstream release reaches every host on the next deploy.
# custom:
#   severity: medium
#   detection: static_analysis
#   examples:
#     bad: |
#       collections:
#         - name: amazon.aws
#     good: |
#       collections:
#         - name: amazon.aws
#           version: ">=9.0.0,<12.0.0"
#     fix: |
#       Add version: with an exact version or a bounded range. A range is enough — what matters is that a new major cannot arrive unannounced.
package greensecops.iac_ansible.reliability.galaxy_requirement_unpinned

import data.greensecops.lib.ansible as ans
import rego.v1

_sections := {"collections", "roles"}

# A mapping entry that names no version.
_unpinned(entry) := name if {
	is_object(entry)
	name := entry.name
	not entry.version
}

# The shorthand form, `- amazon.aws`, which can carry no version at all.
_unpinned(entry) := entry if is_string(entry)

# The shorthand form is a bare string, so it carries no stamped line of its own.
_line(entry) := object.get(entry, "__start_line__", null) if is_object(entry)

_line(entry) := null if not is_object(entry)

violations contains violation if {
	some f in input.files
	some section in _sections
	some entry in object.get(ans.requirements_of(f), section, [])
	name := _unpinned(entry)
	violation := {
		"rule": "galaxy_requirement_unpinned",
		"severity": "medium",
		"category": "reliability",
		"file_path": ans.path(f),
		"line_start": _line(entry),
		"line_end": _line(entry),
		"task_name": "",
		"discriminator": sprintf("%v/%v", [section, name]),
		"message": sprintf("Galaxy %v '%v' has no version — every install takes whatever Galaxy currently serves.", [section, name]),
	}
}
