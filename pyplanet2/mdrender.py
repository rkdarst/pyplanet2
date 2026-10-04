"""Markdown for the one piece of prose the site itself owns.

Everything else on the page comes from feeds and is sanitized as such.
``site.intro`` in the config is the operator's own text -- what the
aggregator is, who runs it, what the rules are -- written in markdown
because that is how a person writes a paragraph with a link in it.
This module turns that text into HTML and decides nothing else: it
touches no files and enforces no policy, so the question of which tags
may survive stays in one place, core.sanitize_html().

Two choices are worth knowing before writing the config:

* Python-Markdown with ``fenced_code`` and nothing more -- no tables,
  footnotes or table of contents.  A site note wants paragraphs,
  emphasis, links, lists and the odd blockquote; every extra extension
  is another syntax to document and another path into the page.
* Headings come out one level down, so a ``#`` in the note is an
  ``<h2>``: the page's only ``<h1>`` is its title, and a note that
  opens with ``#`` would otherwise outrank it.  ``######`` stays an
  ``<h6>``, and a heading written as literal HTML is left alone -- that
  is markup handed over, not something to rewrite.

A blank line separates paragraphs: a single newline inside a paragraph
is markdown for "continue the sentence", which surprises everyone once.

The file is not called markdown.py, whatever it is about: a module by
that name inside a package that imports the markdown library invites
the wrong one to be loaded.
"""
import markdown
from markdown.extensions import Extension
from markdown.treeprocessors import Treeprocessor

HEADINGS = {"h1", "h2", "h3", "h4", "h5", "h6"}


class HeadingLevels(Extension):
    """Render markdown headings one level below what they are written at."""

    def extendMarkdown(self, md):
        class _Shift(Treeprocessor):
            def run(self, root):
                for element in root.iter():
                    tag = getattr(element, "tag", None)
                    if tag in HEADINGS:
                        element.tag = "h{}".format(min(6, int(tag[1:]) + 1))

        md.treeprocessors.register(_Shift(md), "shift_headings", 15)


def render_markdown(text):
    """HTML for a block of markdown, unsanitized.

    The caller sanitizes: this is markup from the config, which is
    trusted input, but the page carries the same allow-list for it as
    for a feed's HTML so there is exactly one answer to what may appear
    on the site.  Empty or whitespace-only text renders as nothing, so
    ``intro: ""`` and no key at all look the same on the page.
    """
    if not text or not text.strip():
        return ""
    return markdown.markdown(text, extensions=["fenced_code",
                                               HeadingLevels()])
