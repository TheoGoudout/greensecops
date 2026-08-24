# METADATA
# title: Package installed ad hoc rather than from a manifest
# description: "A run step installs a package by name, outside any lockfile or manifest. What gets installed is then whatever the registry serves that day, so the same commit builds differently over time and a compromised or yanked release enters the build with no record of the change. The distinction this rule draws is between a command that resolves against a file in the repository — `npm ci`, `pip install -r`, a pinned version — and one that resolves against the registry's idea of current."
# custom:
#   severity: low
#   severity_weight: 0.6
#   detection: static_analysis
#   examples:
#     bad: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm install -g typescript
#             - run: go install github.com/mikefarah/yq/v4@latest
#     good: |
#       jobs:
#         build:
#           runs-on: ubuntu-latest
#           steps:
#             - run: npm ci
#             - run: go install github.com/mikefarah/yq/v4@v4.44.3
#     fix: |
#       Pin what the command installs, or move it into a manifest the repository owns. `npm install -g pkg` becomes a devDependency installed by `npm ci`; `go install …@latest` becomes `…@v1.2.3`; `pip install pkg` becomes `pip install "pkg>=1.2,<2"` or `-r requirements.txt`; `cargo install pkg` becomes `cargo install --locked pkg`; `gem install pkg` becomes `gem install -v 1.2.3 pkg`. Keep the version where a human can see it change in a diff.
package greensecops.ci_workflow.maintainability.adhoc_package_install

import rego.v1

# Comments are stripped first, so an install command shown in a `#` line is not
# reported — the same treatment `insecure_url_scheme` gives its URLs.
_code(run) := regex.replace(run, `#[^\n]*`, "")

# A global npm/yarn install. The local forms resolve against package.json, so
# only `-g`/`--global` is ad hoc.
_adhoc(script, "npm") if {
	regex.match(`(?:^|[\s;&|(])(?:npm|pnpm|bun|yarn)\s+(?:install|i|add)\s+[^\n]*(?:-g|--global)\b`, script)
}

# `go install …@latest` names a moving target explicitly; any other `@version`
# is a pin.
_adhoc(script, "go") if {
	regex.match(`(?:^|[\s;&|(])go\s+install\s+[^\n]*@latest\b`, script)
}

# `cargo install` ignores the crate's own Cargo.lock unless told not to, which
# is what `--locked` is for.
_adhoc(script, "cargo") if {
	regex.match(`(?:^|[\s;&|(])cargo\s+install\b`, script)
	not regex.match(`(?:^|[\s;&|(])cargo\s+install\s[^\n]*--locked\b`, script)
}

_adhoc(script, "gem") if {
	regex.match(`(?:^|[\s;&|(])gem\s+install\b`, script)
	not regex.match(`(?:^|[\s;&|(])gem\s+install\s[^\n]*(?:-v|--version)\b`, script)
}

# `pip install` is ad hoc only when it resolves nothing from the repository: no
# requirements or constraints file, no local path, no version specifier of any
# kind, and no shell variable holding one. This repository's own workflows run
# `pip install "ruamel.yaml>=0.18,<0.19"` and `pip install "ansible-core${VER}"`
# — both are pinned, and a rule that reported them would be wrong about the
# corpus it ships with.
_adhoc(script, "pip") if {
	regex.match(`(?:^|[\s;&|(])(?:pip|pip3|uv\s+pip)\s+install\b`, script)
	not regex.match(`(?:^|[\s;&|(])(?:pip|pip3|uv\s+pip)\s+install\s[^\n]*(?:-r|-c|--requirement|--constraint|-e|--editable)\b`, script)
	not regex.match(`(?:^|[\s;&|(])(?:pip|pip3|uv\s+pip)\s+install\s[^\n]*(?:==|>=|<=|~=|!=|>|<|\$)`, script)
	not regex.match(`(?:^|[\s;&|(])(?:pip|pip3|uv\s+pip)\s+install\s+(?:[^\n]*\s)?\.(?:\s|$)`, script)
}

violations contains violation if {
	some job_name, job in input.jobs
	some step_index, step in job.steps
	script := step.run
	is_string(script)
	some ecosystem in ["npm", "go", "cargo", "gem", "pip"]
	_adhoc(_code(script), ecosystem)

	step_label := object.get(step, "name", "unnamed step")
	violation := {
		"rule": "adhoc_package_install",
		"severity": "low",
		"category": "maintainability",
		"job": job_name,
		"step_index": step_index,
		"message": sprintf("Step '%v' in job '%v' installs a %v package ad hoc, so the build resolves it against the registry rather than against anything in the repository and changes without a commit. Pin the version, or move the dependency into a manifest the build already reads.", [step_label, job_name, ecosystem]),
		"context": ecosystem,
		"discriminator": sprintf("%v:%v:%v", [job_name, step_index, ecosystem]),
	}
}
