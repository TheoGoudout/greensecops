# GreenSecOps: Pull Request Labels

**When to use:** Creating a GitHub PR in this repo (`gh pr create` or the `pr`/`prp-pr` skill).

## Rule

CI job `check-labels` (`.github/workflows/labeler.yml`, `agilepathway/label-checker`) requires
**exactly one** label from this set on every PR — it fails the check if none match:

```
breaking, security, feature, bug, refactor, upgrade, docs, lang-all, internal
```

Source of truth: `one_of:` list in `.github/workflows/labeler.yml`. If that list changes, update
this file to match.

## Applying the label

`actions/labeler` (same workflow) auto-applies `docs`, `upgrade`, `internal` from
`.github/labeler.yml` path-based rules — but only on `docs`/`upgrade`/`internal` shaped diffs.
For anything else (`breaking`, `security`, `feature`, `bug`, `refactor`, `lang-all`), the label
won't be auto-applied and must be set explicitly when creating the PR:

```bash
gh pr create --title "..." --body "..." --label feature
```

Or after creation:

```bash
gh pr edit <PR#> --add-label bug
```

## Picking the label

Match the PR's Conventional Commit type to a label:

| Commit type | Label |
|---|---|
| `feat` | `feature` |
| `fix` | `bug` |
| `refactor` | `refactor` |
| `docs` | `docs` (usually auto-applied) |
| `chore` (deps bump) | `upgrade` (usually auto-applied) |
| `chore`/`ci` (repo-internal, non-doc) | `internal` (usually auto-applied) |
| breaking change (any type) | `breaking` |
| security fix | `security` |
| i18n/translation | `lang-all` |

If path-based auto-labeling already covers it (check `gh pr view <PR#> --json labels` after
opening), no manual `--label` needed. Otherwise add one manually before/at PR creation so
`check-labels` passes on first run.
