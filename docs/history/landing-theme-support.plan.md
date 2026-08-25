# Plan: Light/Dark/Auto Theme Support for Landing Site

**Source**: TODO.md (Improvement #5)
**Complexity**: Small

## Summary
`landing/` is 4 static HTML pages (index, pricing, privacy, terms) served by nginx, no build step, no JS framework — only `envsubst` at container start for `${APP_URL}` etc. It currently has no theme switching; `assets/style.css` only defines light-mode tokens. The dashboard app (`frontend/`) already has a complete dark-token set and a `theme-provider.tsx` (`system`/`light`/`dark`, `localStorage`, `prefers-color-scheme` listener, class toggle on `<html>`). Port that same token set and switching logic to plain CSS/JS since landing has no React/bundler. `landing/assets/images/logo-mark-dark.png` already exists but is unused — wire it up.

## Patterns to Mirror
| Category | Source | Pattern |
|---|---|---|
| Dark tokens | `frontend/src/index.css:164-230` | `.dark { --background: ...; --card: ...; --grade-*; --sev-*; }` overrides on top of `:root` |
| Theme resolution | `frontend/src/components/theme-provider.tsx:41-70` | `system` → `matchMedia("(prefers-color-scheme: dark)")`, else explicit; toggle `.light`/`.dark` class on `documentElement` |
| Persistence | `frontend/src/components/theme-provider.tsx:37-38,96-97` | `localStorage.getItem(storageKey)`, default `"system"` |
| Toggle UI | `frontend/src/components/Common/Appearance.tsx:77-96` | Sun/Moon icon button + dropdown with Light/Dark/System items |
| Nav markup (all 4 pages) | `landing/index.html:15-30`, same block in `pricing.html:15-31`, `privacy.html`, `terms.html` | Identical `<header><nav class="nav">...<div class="nav__links">` duplicated verbatim across files — must edit all 4 |
| Button/icon styling | `landing/assets/style.css:196-268` | `.btn`, `.btn--ghost`, `.btn--sm` classes to mirror for the new toggle button |

## Files to Change
| File | Action | Why |
|---|---|---|
| `landing/assets/style.css` | UPDATE | Add `.dark { ... }` token overrides (mirror `frontend/src/index.css`), no-FOUC-safe defaults, toggle button styles, `<img>` swap rule for logo |
| `landing/assets/theme.js` | CREATE | Vanilla JS: resolve theme (`system`/`light`/`dark`), apply `.dark`/`.light` class on `<html>` before first paint, persist to `localStorage`, listen for `prefers-color-scheme` changes, wire toggle button clicks |
| `landing/index.html` | UPDATE | Inline blocking `<script>` in `<head>` (pre-paint theme apply, avoids flash), add theme-toggle button in nav, `<script src="./assets/theme.js" defer>`, swap logo `<img>` for dark variant via CSS |
| `landing/pricing.html` | UPDATE | Same head script + nav toggle button as index.html |
| `landing/privacy.html` | UPDATE | Same head script + nav toggle button |
| `landing/terms.html` | UPDATE | Same head script + nav toggle button |

## Tasks

### Task 1: Dark tokens in `assets/style.css`
- **Action**: Add `.dark { --background, --foreground, --card, --border, --muted-foreground, --primary, --accent, --grade-*-bg/fg, --shadow-* }` block mirroring `frontend/src/index.css:164-230`, adapted to landing's flatter token set (landing has no `--popover`/`--sidebar-*`/`--chart-*`, skip those). Keep `:root` (light) values unchanged.
- **Mirror**: `frontend/src/index.css:164-230`
- **Validate**: `grep -c "^\.dark" landing/assets/style.css` → 1; visually diff light vs dark background/text contrast

### Task 2: Theme toggle button styles + logo swap
- **Action**: Add `.theme-toggle` button (icon-only, mirrors `.btn--ghost.btn--sm` sizing) with sun/moon SVG shown/hidden via `.dark` class the same way `Appearance.tsx:85-86` does with Tailwind `dark:` variants — plain CSS equivalent: `.theme-toggle .icon-sun { display: block } .dark .theme-toggle .icon-sun { display: none }` (and inverse for moon). Add `.nav__logo img { content: ...}`-style swap: show `logo-mark.png` in light, `logo-mark-dark.png` in dark (use two `<img>` tags toggled via the same display rule, since `content` swap has poor browser support for `<img>`).
- **Mirror**: `landing/assets/style.css:196-268` (`.btn` family), `frontend/src/components/Common/Appearance.tsx:85-86`
- **Validate**: Toggle button visible in nav, correct icon/logo per theme

### Task 3: `assets/theme.js`
- **Action**: Vanilla JS module implementing the same resolution as `theme-provider.tsx`: read `localStorage.getItem("theme")` (default `"system"`), compute resolved theme, set `document.documentElement.classList` to `light`/`dark`, attach `prefers-color-scheme` `change` listener (only acts when stored preference is `"system"`), wire dropdown/button clicks to call `setTheme` + persist. Reuse the same 3-state model (`light`/`dark`/`system`).
- **Mirror**: `frontend/src/components/theme-provider.tsx:41-98`
- **Validate**: Manual: toggle each of the 3 options, reload page, confirm persistence; toggle OS theme while `system` selected, confirm live update

### Task 4: Wire into all 4 HTML pages
- **Action**: In each of `index.html`, `pricing.html`, `privacy.html`, `terms.html`:
  1. Add a **synchronous inline** `<script>` in `<head>` (before `style.css` link, or right after) that reads `localStorage` and sets the class immediately — prevents flash-of-wrong-theme on load (same reason SPAs run this pre-hydration).
  2. Add the toggle button markup inside `.nav__links`, before or after the existing links.
  3. Add `<script src="./assets/theme.js" defer></script>` before `</body>`.
- **Mirror**: existing nav block duplicated identically across the 4 files (`landing/index.html:15-30`)
- **Validate**: Load each of the 4 pages directly, confirm no flash, toggle works identically on all

### Task 5: E2E coverage
- **Action**: No existing test harness covers `landing/` (checked — no Playwright specs reference it). Add a minimal Playwright spec `frontend/tests/landing-theme.spec.ts` (or a project-specific config if `landing/` needs its own static server) that serves the 4 static files and asserts: default is system-resolved, clicking each toggle option updates `<html>` class + persists across reload, works on all 4 pages.
- **Mirror**: `frontend/tests/dashboard.spec.ts` for Playwright conventions (already in repo)
- **Validate**: `npx playwright test landing-theme.spec.ts`

## Validation
```bash
# static serve for manual check
python3 -m http.server 8080 --directory landing
# then hit http://localhost:8080/{index,pricing,privacy,terms}.html and toggle

# once Task 5 lands
cd frontend && npx playwright test landing-theme.spec.ts
```

## Risks
| Risk | Likelihood | Mitigation |
|---|---|---|
| Flash of wrong theme on load (FOUC) | High if inline pre-paint script skipped | Task 4's inline head script must run synchronously before CSS paint, not deferred |
| Drift between landing tokens and dashboard tokens (style.css comment claims "mirrors frontend/src/index.css exactly" — already slightly stale) | Medium | Keep the two `.dark` blocks side by side when reviewing; note in style.css comment which tokens landing intentionally omits |
| `envsubst` in `entrypoint.sh` only substitutes a fixed var allowlist (`${APP_URL} ${DOCS_URL} ...`) | Low | New inline script/JS must not introduce `${APP_URL}`-shaped tokens outside that allowlist — fine as long as theme.js has no `${}` template literals matching those names |
| No existing test/server infra for `landing/` | Medium | Task 5 may need a lightweight static-file Playwright `webServer` config entry rather than reusing the Vite dev server |

## Acceptance
- [ ] All 4 pages support light/dark/auto, no FOUC
- [ ] Preference persists across reload (own storage key, not shared with dashboard app — different origins)
- [ ] `logo-mark-dark.png` used in dark mode
- [ ] Toggle button styled consistently with existing `.btn` family
- [ ] Playwright spec passes
