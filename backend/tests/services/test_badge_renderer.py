from app.services.badge_renderer import render_badge, render_unknown_badge


def test_render_badge_contains_grade() -> None:
    svg = render_badge("A+++")
    assert "A+++" in svg
    assert "<svg" in svg
    assert "GreenSecOps" in svg


def test_render_badge_uses_correct_color() -> None:
    svg = render_badge("F")
    assert "#991B1B" in svg


def test_render_badge_a_plus_plus_plus_color() -> None:
    svg = render_badge("A+++")
    assert "#10B981" in svg


def test_render_unknown_badge() -> None:
    svg = render_unknown_badge()
    assert "<svg" in svg
    assert "?" in svg


def test_render_badge_valid_svg_structure() -> None:
    svg = render_badge("B")
    assert svg.startswith("<svg")
    assert "</svg>" in svg
