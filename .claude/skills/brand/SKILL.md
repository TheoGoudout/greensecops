---
name: brand
description: Apply GreenSecOps' visual identity (forest green + cyan OKLCH tokens, signal gradient, grade/severity scales, Space Grotesk + Inter + JetBrains Mono, dark console sidebar). Use when styling new UI, choosing colors, or reviewing visual changes.
---

# Visual identity

Authoritative source: `VISUAL_IDENTITY.md` at the repo root. This is the
short version.

## The feel

A security console: precise, dense, calm, a little futuristic. Colour carries
meaning; chrome stays neutral.

## Colour: tokens only

Tokens live in `frontend/src/index.css` and map to Tailwind classes. Never
hardcode hex or add new Tailwind palette classes in components.

| Token | Use |
|-------|-----|
| `primary` | Forest green / mint: primary actions, links, focus, active item |
| `accent` | Cyan: secondary emphasis. White text on it is 3.3:1 — icons or bold 18px+ only |
| `bg-signal` / `text-signal` | The green→cyan gradient: header rule, primary buttons, dashboard title. Nowhere else, never on data |
| `--signal-1`…`--signal-4` | Stat-tile accents (pass as `StatCard` `tone`), fixed per stat |
| `chart-1`…`chart-8`, `heat-1`…`heat-4` | Data series; heat is the heatmap ramp |
| `muted`, `border`, `card`, `background` | Neutral chrome |

Grade (A+++→F: emerald→red) and severity (critical red, high orange, medium
yellow, low blue, info muted) scales live in `GradeBadge`, `SeverityChip`,
`lib/engine-meta.ts` and `lib/file-viewer.ts` — reuse those components, and
change a scale in all of them together. Always show the label with the colour.

## Typography

- `font-display` — Space Grotesk: `h1`–`h3` (automatic), stat values.
- `font-sans` — Inter: everything else.
- `font-mono` — JetBrains Mono: code, rule ids, paths, versions, and column
  headers (`font-mono uppercase tracking-wider text-xs`; shadcn tables get it
  automatically).
- Fonts are bundled from `@fontsource-variable/*`. Never add a font-CDN link.

## Shape and texture

- Radius `0.5rem`; borders over shadows.
- `bg-tech-grid` behind pages (already on the layout and auth screens).
- The sidebar is dark in both themes; use `<Logo onDark />` on dark surfaces.

## Primitives

`frontend/src/components/ui/` is shadcn-generated: don't edit it. Style at
the call site or with the base-layer selectors in `index.css`.
