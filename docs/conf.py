import os
import sys

sys.path.insert(0, os.path.abspath("ext"))

project = "GreenSecOps"
copyright = "2026, GreenSecOps"
author = "GreenSecOps"

extensions = ["rego_autodoc"]

html_theme = "furo"
html_title = "GreenSecOps Rules"
html_baseurl = os.environ.get("DOCS_BASE_URL", "")
html_static_path = ["_static"]
html_css_files = ["custom.css"]
html_theme_options = {
    "light_logo": "logo-mark.png",
    "dark_logo": "logo-mark-dark.png",
}

exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]
