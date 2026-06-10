_GRADE_COLORS: dict[str, str] = {
    "A+++": "#10B981",
    "A++": "#22C55E",
    "A+": "#84CC16",
    "A": "#A3E635",
    "B": "#F59E0B",
    "C": "#FB923C",
    "D": "#EF4444",
    "F": "#991B1B",
}

_SVG_TEMPLATE = """\
<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" \
width="{total_width}" height="20" role="img" aria-label="GreenSecOps: {grade}">
  <title>GreenSecOps: {grade}</title>
  <linearGradient id="s" x2="0" y2="100%">
    <stop offset="0" stop-color="#bbb" stop-opacity=".1"/>
    <stop offset="1" stop-opacity=".1"/>
  </linearGradient>
  <clipPath id="r"><rect width="{total_width}" height="20" rx="3" fill="#fff"/></clipPath>
  <g clip-path="url(#r)">
    <rect width="{label_width}" height="20" fill="#555"/>
    <rect x="{label_width}" width="{value_width}" height="20" fill="{color}"/>
    <rect width="{total_width}" height="20" fill="url(#s)"/>
  </g>
  <g fill="#fff" text-anchor="middle" \
font-family="DejaVu Sans,Verdana,Geneva,sans-serif" font-size="110">
    <text x="{label_center}0" y="150" fill="#010101" fill-opacity=".3" \
transform="scale(.1)" textLength="{label_text_width}" lengthAdjust="spacing">GreenSecOps</text>
    <text x="{label_center}0" y="140" transform="scale(.1)" \
textLength="{label_text_width}" lengthAdjust="spacing">GreenSecOps</text>
    <text x="{value_center}0" y="150" fill="#010101" fill-opacity=".3" \
transform="scale(.1)" textLength="{value_text_width}" lengthAdjust="spacing">{grade}</text>
    <text x="{value_center}0" y="140" transform="scale(.1)" \
textLength="{value_text_width}" lengthAdjust="spacing">{grade}</text>
  </g>
</svg>"""


def render_badge(grade: str) -> str:
    color = _GRADE_COLORS.get(grade, "#9CA3AF")
    label_width = 100
    value_width = 40 + len(grade) * 6
    total_width = label_width + value_width
    label_center = label_width // 2
    value_center = label_width + value_width // 2
    label_text_width = 860
    value_text_width = max(180, len(grade) * 60)

    return _SVG_TEMPLATE.format(
        total_width=total_width,
        label_width=label_width,
        value_width=value_width,
        color=color,
        label_center=label_center,
        value_center=value_center,
        label_text_width=label_text_width,
        value_text_width=value_text_width,
        grade=grade,
    )


def render_unknown_badge() -> str:
    return render_badge("?")
