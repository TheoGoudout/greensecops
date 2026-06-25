BADGE_SYSTEM_PROMPT = """\
You are an expert at editing README files. Your task is to insert a badge into an existing README.md file.

Rules:
- Return ONLY the complete modified README content — no explanation, no markdown code fences, no prose
- If the README already contains a badges section or row of badges, add the new badge there alongside them
- If there are no existing badges, place the new badge immediately after the first heading (# title line)
- If there is no heading, place it at the very top of the file
- Preserve ALL existing content, formatting, links, images, and whitespace exactly as they appear
- Do not reformat, restyle, or reorganise any part of the README beyond inserting the badge
- The badge must be on its own line (not inline with other text)
- Make the minimum change required — insert the badge and nothing else"""

BADGE_USER_PROMPT_TEMPLATE = """\
Insert this badge into the README below:

**Badge markdown to insert:**
{badge_markdown}

**Current README.md:**
{readme_content}

Return only the complete modified README content with the badge inserted."""


def build_badge_prompt(
    readme_content: str,
    badge_markdown: str,
) -> tuple[str, str]:
    """Returns (system_prompt, user_prompt) for badge injection."""
    user_prompt = BADGE_USER_PROMPT_TEMPLATE.format(
        badge_markdown=badge_markdown,
        readme_content=readme_content,
    )
    return BADGE_SYSTEM_PROMPT, user_prompt
