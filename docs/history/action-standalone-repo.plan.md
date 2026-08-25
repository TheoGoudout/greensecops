# Plan: Extract Telemetry Action to a Standalone Public Repo + Release CI

**Source**: TODO.md (Feature #1)
**Complexity**: Medium-Large (touches external infra: a new public GitHub repo + a cross-repo push credential)

## Summary
`action/` (`backend`-adjacent, `TheoGoudout/greensecops:action/`) is already a fully self-contained bun/TypeScript project — its own `package.json`, `biome.json`, `tsconfig.json`, `.pre-commit-config.yaml`, and even a **pre-staged but currently-dead** `action/.github/workflows/ci.yml` (GitHub only reads workflows from a repo's *root* `.github/workflows/`, so this file is inert inside the monorepo — it was clearly scaffolded in anticipation of exactly this extraction). The live CI today is the root-level `.github/workflows/test-action.yml`, path-filtered to `action/**`.

Two separate concerns, only one of which is today's CI-job deliverable:
1. **One-time bootstrap** (manual, not CI): create the new public repo, preserve `action/`'s existing git history into it via `git subtree split`, push that as its initial `main`. This is an external, hard-to-reverse, visible-to-others action — I will do this interactively with you when you're ready, not as an unattended step.
2. **Ongoing sync CI job** (the actual deliverable): keep the public repo's `main` up to date with the monorepo's `action/` on every push to `main`, and cut a matching tagged release on the public repo whenever a release/pre-release is published on the monorepo. This is what gets built now.

## Decisions already made (from your answers)
| Question | Answer |
|---|---|
| Target repo | Not hardcoded — read from a CI variable (`vars.ACTION_PUBLIC_REPO`, e.g. `TheoGoudout/greensecops-action`) so it's configurable without a code change |
| History | Preserve — use `git subtree` (split once for bootstrap, `push` incrementally in CI) rather than a fresh single commit |
| Trigger | Sync on every push to `main` (paths: `action/**`) **and** on `release`/`prerelease` published events |

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Path-filtered workflow | `.github/workflows/test-action.yml:1-13` | `on.push.paths` / `on.pull_request.paths: ["action/**"]`, `defaults.run.working-directory: action` |
| SHA-pinned actions | `.github/workflows/test-action.yml:20,24,28` | Every `uses:` pinned to a full 40-char commit SHA with a `# vX.Y.Z` comment — required by our own `unpinned_actions`/`untrusted_actions` rego rules; a new workflow that violated them would be embarrassing |
| Named secrets for privileged cross-repo tokens | `.github/workflows/pre-commit.yml:13,35`, `latest-changes.yml:37` | `secrets.PRE_COMMIT`, `secrets.LATEST_CHANGES` — custom PAT-shaped secrets for operations `GITHUB_TOKEN` can't do (here: pushing to a *different* repo) |
| CI-variable config (not hardcoded) | `.github/workflows/docs.yml:36` | `${{ vars.DOCS_BASE_URL }}` — same mechanism to use for `vars.ACTION_PUBLIC_REPO` |
| Bundling for distribution | `action/package.json:6` | `ncc build src/{pre,main,post,daemon}.ts -o dist/... --minify` — already produces exactly the `dist/pre|main|post/index.js` that `action.yml:15-17` references |
| Already-prepared standalone CI | `action/.github/workflows/ci.yml` | Nearly production-ready lint/typecheck/test/build pipeline for the *extracted* repo — reuse almost verbatim as the target repo's own CI, don't reinvent it |

## Files to Change
| File | Action | Why |
|---|---|---|
| `.github/workflows/sync-action-repo.yml` | CREATE | New root-level workflow: subtree-push `action/` to the public repo on every `main` push; additionally tag + publish a GitHub release there on `release`/`prerelease` events |
| `action/.gitignore` | No monorepo change | `dist` stays gitignored *here* — the sync job builds `dist/` inside a separate checkout of the **public** repo, not the monorepo, so this file is untouched |
| (external) public repo root `.gitignore` | CREATE (in the new repo, not this one) | Must **not** ignore `dist/` — consumers run the committed bundle directly, no build step |

## Tasks

### Task 1: Bootstrap the public repo (manual, interactive, done together — not unattended CI)
- **Action**: Once you've created the empty public repo and told me its `owner/repo`, I run locally (not from this session unattended): `git subtree split --prefix=action -b action-history` on the monorepo, then push `action-history` as `main` to the new repo. This is the one time full history gets rewritten from scratch.
- **Validate**: New repo's commit log shows the same authorship/messages as `git log -- action/` in the monorepo, `action.yml`/`src/` present at the new repo root (not nested under `action/`).

### Task 2: Add the CI variable + secret
- **Action**: In the monorepo's GitHub repo settings — add `vars.ACTION_PUBLIC_REPO` = `owner/repo`, and a fine-grained PAT scoped to **only** that target repo with `contents: write`, stored as `secrets.ACTION_PUBLIC_REPO_TOKEN`. (I can talk you through creating the fine-grained PAT, but creating tokens/secrets in repo settings is something you do directly — I don't have a way to do this for you.)
- **Validate**: `gh secret list` / `gh variable list` on the monorepo show both, no plaintext token ever committed.

### Task 3: `.github/workflows/sync-action-repo.yml` — sync job
- **Action**: New workflow, two triggers:
  - `push: branches: [main], paths: [action/**]` → sync only
  - `release: types: [published, prereleased]` → sync + tag + release
  - `workflow_dispatch:` → manual re-run escape hatch
  Job steps (mirroring Task-1's tool, done incrementally instead of a full split):
  1. Checkout monorepo, `fetch-depth: 0`, `persist-credentials: false` (per `test-action.yml` convention).
  2. Configure a bot git identity.
  3. `git remote add public-action https://x-access-token:${{ secrets.ACTION_PUBLIC_REPO_TOKEN }}@github.com/${{ vars.ACTION_PUBLIC_REPO }}.git`
  4. `git subtree push --prefix=action public-action main` — pushes only new commits touching `action/` since the last sync, preserving per-file history.
  5. Separate step: checkout the **public** repo fresh (`actions/checkout` with `repository: ${{ vars.ACTION_PUBLIC_REPO }}`, `token: secrets.ACTION_PUBLIC_REPO_TOKEN`), `bun install && bun run build`, force-add `dist/` (it's gitignored by default even there — force-add is intentional and expected for compiled GH Action bundles, this is the standard `actions/*` convention), commit `chore: rebuild dist for ${{ github.sha }}`, push to `main` if there's a diff.
- **Mirror**: `test-action.yml`'s bun setup/cache steps; `action/.github/workflows/ci.yml`'s lint/typecheck/test/build sequence for the build step specifically.
- **Validate**: Push a trivial `action/` change to monorepo `main` → public repo `main` gains the same commit + an auto-`dist` rebuild commit.

### Task 4: Tag + release on `release`/`prerelease` events
- **Action**: When triggered by a monorepo release event, after Task 3's sync: read `github.event.release.tag_name`, create/force-move that tag **and** the floating major tag (e.g. `v1`) on the public repo pointing at the freshly-pushed `dist` commit, then `gh release create <tag> --repo ${{ vars.ACTION_PUBLIC_REPO }} --prerelease=<bool from event>` mirroring the monorepo release's prerelease flag and notes.
- **Mirror**: GitHub's own documented convention for publishing a Marketplace-listed action (SHA-pinned consumers use the exact tag; floating `v1` users track latest within a major).
- **Validate**: Publish a pre-release on the monorepo → public repo gets a matching tag + GitHub release marked prerelease.

### Task 5: Zizmor / security pass on the new workflow
- **Action**: This repo runs `zizmor.yml` (a GH Actions security linter) in CI. Run it locally against the new workflow before merging: SHA-pin every `uses:`, avoid `pull_request_target`, scope `permissions:` minimally (only `contents: read` on the monorepo checkout; the cross-repo write happens via the PAT, not `GITHUB_TOKEN`), and confirm no secret is ever echoed to logs.
- **Validate**: `zizmor .github/workflows/sync-action-repo.yml` (or however the local pre-commit hook invokes it) passes clean.

## Validation
```bash
# local dry run of the build step, without pushing anywhere
cd action && bun install && bun run build && ls dist/pre dist/main dist/post

# once the workflow exists
gh workflow run sync-action-repo.yml --repo TheoGoudout/greensecops
gh run watch --repo TheoGoudout/greensecops
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| PAT over-scoped (org-wide instead of repo-specific) | Medium | Use a fine-grained PAT scoped to exactly the one target repo, `contents: write` only |
| `git subtree push` conflicts if the public repo's `main` was ever hand-edited directly | Low | Treat the public repo as CI-owned; document "don't push directly to main" in its README |
| Committing `dist/` drifts from `src/` if the build step is skipped/fails silently | Medium | Fail the job (not warn) if `git diff --exit-code dist` after build differs from what was expected; no silent partial sync |
| Release tag race if two releases publish close together | Low | Job is not concurrency-grouped by design (each release is independent) but uses the immutable `github.event.release.tag_name`, not "latest" |
| First-ever run has no prior sync history for `git subtree push` to diff against | Low | Task 1's manual bootstrap must land before Task 3's CI job is enabled, else the first `subtree push` has nothing to reconcile against |

## Acceptance
- [ ] Public repo exists with full preserved history for `action/` up to the bootstrap point
- [ ] `vars.ACTION_PUBLIC_REPO` + `secrets.ACTION_PUBLIC_REPO_TOKEN` configured
- [ ] Every push to monorepo `main` touching `action/**` syncs the public repo within minutes
- [ ] Every monorepo release/pre-release produces a matching tag + GitHub release on the public repo, with `dist/` rebuilt and committed
- [ ] New workflow passes zizmor and uses only SHA-pinned actions
