# GreenSecOps — Visual Identity

The graphical chart for the web app. The tokens it describes live in
`frontend/src/index.css`; this document says what they are for.

## Who it is for, and how it should feel

DevOps, platform and security engineers grading their delivery pipelines.
They scan dense information quickly, live in terminals and dashboards, and
distrust anything that looks like marketing.

**Precise · Technical · Calm · Trustworthy** — with a little future in it.

It should feel like a well-built security console: dark-first, dense,
instrument-panel typography, one signal colour that lights up what matters.
Colour carries meaning (grade, severity, category) and the chrome stays out
of the way. The futuristic touches (the signal gradient, the grid, the lit
rail) are seasoning, not the dish.

**Do**
- Let the data speak: grades, severities and scores get the colour; the
  layout stays neutral.
- Use monospace for anything a machine produced: rule ids, paths, branches,
  versions, column headers.
- Keep density: tables over cards when there are more than a handful of rows.

**Don't**
- Don't add neon or glow beyond the primary button and the active nav rail.
- Don't use the signal gradient on data, or on more than one heading a page.
- Don't introduce new hues: a new state maps onto the existing scales.

## Colour

Tokens are OKLCH in `frontend/src/index.css` (`:root` light, `.dark` dark),
exposed to Tailwind (`bg-primary`, `text-muted-foreground`…). Never hardcode
hex in components. Hex values below are approximations for design tools.

### Brand

| Token | Light | Dark | Role |
|---|---|---|---|
| `--primary` | `oklch(0.5 0.13 156)` ≈ `#007842` forest green | `oklch(0.78 0.17 158)` ≈ `#31D78C` mint | The leaf in the logo: primary actions, links, focus, the active item |
| `--accent` | `oklch(0.62 0.14 225)` ≈ `#0096C5` | `oklch(0.72 0.14 220)` ≈ `#00B8E1` | "SecOps" cyan: secondary emphasis, the far end of the signal gradient |
| `--signal` | green → cyan, 90° | brighter in dark | The signature gradient (see below) |

Contrast: white on light primary 5.3:1; dark text on mint 9.6:1. **White on
the light cyan accent is only 3.3:1**, so accent fills carry icons or bold
text of 18px and up, never body copy.

### Surfaces

| Token | Light | Dark |
|---|---|---|
| `--background` | `oklch(0.982 0.004 170)` ≈ `#F7FAF9` mint-white | `oklch(0.155 0.01 180)` ≈ `#080E0C` green-black |
| `--card` | white | `oklch(0.19 0.012 180)` ≈ `#0E1614`, with a faint top sheen |
| `--sidebar` | `oklch(0.18 0.015 175)` ≈ `#0A1411` | `oklch(0.13 0.01 180)` ≈ `#040807` |
| `--border` | `oklch(0.9 0.01 175)` | `oklch(1 0 0 / 8%)` |

The **sidebar is dark in both modes**: the console frame around the work. In
light mode it is the one dark element on the page.

### Signal gradient

`--signal` runs from the logo's green to its cyan. Utilities: `bg-signal`,
`text-signal`. It appears in exactly three places:

1. the 2px rule under the header,
2. primary buttons (a 135° green-to-teal blend, with `--glow-primary`),
3. the dashboard title.

Nowhere else, and never on data.

### Stat accents

`--signal-1` green, `--signal-2` cyan, `--signal-3` amber, `--signal-4`
violet. Each dashboard stat tile owns one (score, findings, fix rate,
coverage) for its icon chip and its 2px top rail. Fixed per stat, never
cycled.

### Meaning scales

These carry the product's vocabulary and must stay consistent everywhere.

| Scale | Values | Colours |
|---|---|---|
| **Grade** | A+++ → F | emerald → green → lime → yellow → orange → red → deep red (like an energy label) |
| **Severity** | critical, high, medium, low, info | red, orange, yellow, blue, muted |
| **Category** | energy, reliability, security, performance, maintainability | amber, sky, red, green, slate |
| **Heat** | `--heat-1`…`--heat-4` | an ordinal red ramp for the findings heatmap, validated per mode |

Grades and severities always show their label next to the colour. Today
their classes live in `components/GradeBadge.tsx`,
`components/SeverityChip.tsx`, `lib/engine-meta.ts` and `lib/file-viewer.ts`
as Tailwind palette steps. Change a scale there, in all of them at once.

### Charts

`--chart-1` … `--chart-8`, in order. `--heat-*` is for the heatmap only.

## Typography

| Role | Family | Where |
|---|---|---|
| Display | **Space Grotesk** (variable) | `h1`–`h3`, stat values, the auth wordmark: `font-display` |
| Body / UI | **Inter** (variable), `cv11` + `ss03` | Everything else: `font-sans` |
| Machine | **JetBrains Mono** (variable) | Code, rule ids, paths, versions, table headers, sidebar section labels: `font-mono` |

Headings track `-0.02em`. **Column headers** and **sidebar section labels**
are mono, uppercase, 11px, letter-spaced: the instrument-panel look. Shadcn
tables get it automatically (`[data-slot="table-head"]`); hand-built grid
headers use `font-mono uppercase tracking-wider text-xs`.

Fonts are bundled from `@fontsource-variable/*` and served from our own
domain: no Google Fonts and no third-party font CDN.

## Shape, depth, texture

- **Radius** `0.5rem`: squarer than a consumer app.
- **Borders over shadows.** Cards are 1px-bordered; depth comes from surface
  steps, not drop shadows.
- **Grid**: `bg-tech-grid` draws a 32px engineering grid with a soft green
  glow at the top, behind every page and the sign-in screen. Lines stay at
  5–7% opacity: felt, not seen.
- **Lit rail**: the active sidebar item gets a 2px `--sidebar-primary` inset
  on its left edge.
- **Motion**: 120–300ms (`--duration-*`) with `--ease-standard`. No bounce.

## Layout

- Sidebar (always dark) with mono section labels: CI/CD Analysis,
  Containers, Infrastructure, Configuration.
- Sticky, translucent header with the signal rule under it.
- Pages: title (dashboard in `text-signal`), one-line description, then a
  row of stat tiles and dense tables.

## Logo

The circuit leaf with "GreenSecOps" (green "Green", cyan "SecOps"), as PNGs
in `frontend/public/assets/images/`: `logo-full`, `logo-mark`, `wordmark`,
each with a `-dark` variant for dark surfaces. `<Logo onDark />` forces the
dark variant (the sidebar uses it in both themes). Don't recolour the logo or
place it on the signal gradient.

## Not yet aligned

- **About 150 Tailwind palette classes** remain in components (the meaning
  scales above, plus older one-offs). New code uses tokens; move the scales
  onto shared tokens when they are next touched.
- The `--green-*`, `--blue-*`, `--grade-*`, `--sev-*` and `--cat-*` CSS
  variables in `index.css` are not referenced by any component. Wire the
  scales to them, or delete them.
- Shadcn menus and ghost buttons hover with `bg-accent text-accent-foreground`,
  so today they show white text on the light cyan (3.3:1). Either darken
  `--accent` in light mode or move hover fills to a neutral token.
- `landing/` still loads Inter and JetBrains Mono from Google Fonts and uses
  its own hex palette.
