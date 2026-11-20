"""PDF stylesheet for mkdocs-with-pdf.

MkDocs Material is the site theme. This handler keeps its print styles and adds
a few overrides that keep long code lines and large diagrams inside the page
box. Without them, WeasyPrint can silently drop the remainder of the manual when
an unbreakable block lands at a page boundary.

Used by mkdocs.pdf-user.yml and mkdocs.pdf-dev.yml via ``theme_handler_path``.
"""

from mkdocs_with_pdf.themes import material


_OVERRIDES = """
/* Keep wide content inside the printable area. */
article img,
article svg {
  max-width: 100% !important;
  height: auto !important;
}

/* Wrap long code lines instead of letting them overflow the page. */
article pre,
article code {
  white-space: pre-wrap !important;
  overflow-wrap: anywhere !important;
  word-break: break-word !important;
}

/* Large tables may span pages; do not force them into one page box. */
article table {
  break-inside: auto !important;
  page-break-inside: auto !important;
}

article tr,
article td,
article th {
  break-inside: avoid !important;
  page-break-inside: avoid !important;
}

/* Mermaid diagrams render as SVG; allow them to break across pages. */
article .mermaid,
article .mermaid svg {
  break-inside: auto !important;
  page-break-inside: auto !important;
}
"""


def get_stylesheet(debug_html: bool) -> str:
    return material.get_stylesheet(debug_html) + _OVERRIDES


def get_script_sources() -> list:
    return material.get_script_sources()


def inject_link(html: str, href: str) -> str:
    return material.inject_link(html, href)
