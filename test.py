"""Tests for pyplanet2.

Run from the repository root with:  pytest

All tests are offline: they only read the sample feeds in test-data/.
"""
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml

from pyplanet2 import fetch_all_items, make_urls_absolute

REPO = Path(__file__).parent

BASE = "https://blog.example.org/2026/09/post.html"


# (html, expected): URL resolution semantics per RFC 3986
CASES = [
    # absolute URLs are left untouched
    ('<img src="https://cdn.example.org/a.png">',
     '<img src="https://cdn.example.org/a.png">'),
    # root-relative resolves against the entry's domain
    ('<img src="/a.png">',
     '<img src="https://blog.example.org/a.png">'),
    # plain relative resolves in the entry's directory
    ('<img src="a.png">',
     '<img src="https://blog.example.org/2026/09/a.png">'),
    # parent-relative resolves up from the entry's directory
    ('<img src="../images/a.png">',
     '<img src="https://blog.example.org/2026/images/a.png">'),
    # protocol-relative inherits the entry's scheme
    ('<img src="//cdn.example.org/a.png">',
     '<img src="https://cdn.example.org/a.png">'),
    # plain anchors untouched
    ('<a href="#frag">x</a>', '<a href="#frag">x</a>'),
    # data: URIs have a scheme and are untouched
    ('<img src="data:image/png;base64,AAAA">',
     '<img src="data:image/png;base64,AAAA">'),
    # links resolve too
    ('<a href="../about.html">x</a>',
     '<a href="https://blog.example.org/2026/about.html">x</a>'),
    # single-quoted attributes
    ("<a href='../about.html'>x</a>",
     "<a href='https://blog.example.org/2026/about.html'>x</a>"),
]

@pytest.mark.parametrize("html, expected", CASES)
def test_make_urls_absolute(html, expected):
    assert make_urls_absolute(html, BASE) == expected


def test_no_base_url_is_noop():
    """Items without a link (base "#") must pass through unchanged."""
    assert make_urls_absolute('<img src="a.png">', "#") == '<img src="a.png">'


def make_feeds_config(tmp_path, resolve_urls):
    """Config for fetch_all_items() over the RSS sample feed."""
    return {
        "feeds": [{
            "url": str(REPO / "test-data" / "rss.xml"),
            "name": "RSS test",
            "resolve_urls": resolve_urls,
        }],
    }


def test_resolve_urls_option(tmp_path):
    """resolve_urls: true rewrites against the item link; default leaves
    feedparser's behavior in place."""
    on = fetch_all_items(make_feeds_config(tmp_path, True))
    assert "http://example.org/images/pic.png" in on[0]["summary"]
    assert "http://example.org/about.html" in on[0]["summary"]

    off = fetch_all_items(make_feeds_config(tmp_path, False))
    # not resolved against the item link (feedparser has no usable base
    # for a local-file feed, so it stays relative or empty -- either way
    # it must not be the entry-based absolute URL)
    assert "http://example.org/images/pic.png" not in off[0]["summary"]


def test_cli_end_to_end(tmp_path):
    """Full command-line run over the local test feeds."""
    config = {
        "site": {
            "title": "Test Planet",
            "site_url": "https://example.com/planet/",
            "atom_feed_url": "https://example.com/planet/atom.xml",
        },
        "output": {
            "atom_feed": str(tmp_path / "atom.xml"),
            "html_view": str(tmp_path / "planet.html"),
            "css": [],
            "logo": "",
        },
        "limits": {"max_feed_items": 100, "html_view_limit": 10},
        "feeds": [
            {"url": str(REPO / "test-data" / "atom.xml"), "name": "Atom test"},
            {"url": str(REPO / "test-data" / "rss.xml"), "name": "RSS test",
             "resolve_urls": True},
        ],
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")

    # cwd in tmp_path so the run cannot depend on the repo layout
    subprocess.run(
        [sys.executable, str(REPO / "pyplanet2.py"), str(config_file)],
        cwd=tmp_path, check=True,
    )

    html_text = (tmp_path / "planet.html").read_text(encoding="utf-8")
    assert "First item title" in html_text

    atom_text = (tmp_path / "atom.xml").read_text(encoding="utf-8")
    ElementTree.fromstring(atom_text)  # raises if not valid XML
    assert "First item title" in atom_text