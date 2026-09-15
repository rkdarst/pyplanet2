"""Tests for pyplanet2.

Run from the repository root with:  pytest

All tests are offline: they only read the sample feeds in test-data/.
"""
import os
import subprocess
import sys
from pathlib import Path
from xml.etree import ElementTree

import pytest
import yaml

from pyplanet2.pyplanet2 import fetch_all_items, make_urls_absolute, safe_link
from pyplanet2 import imagecache
from pyplanet2.imagecache import localize_images, rewrite_images

REPO = Path(__file__).parent.parent  # tests live in pyplanet2/ of the checkout

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


def make_atom_config(**feed_opts):
    """Config for fetch_all_items() over the Atom sample feed."""
    feed = {"url": str(REPO / "test-data" / "atom.xml"), "name": "Atom test"}
    feed.update(feed_opts)
    return {"feeds": [feed]}


def test_content_preferred_over_summary(tmp_path):
    """Full Atom <content> wins over the short <summary> by default."""
    items = fetch_all_items(make_atom_config())
    assert "CONTENT-MARKER" in items[0]["summary"]


def test_prefer_summary_option(tmp_path):
    """prefer_summary: true keeps the short teaser instead."""
    items = fetch_all_items(make_atom_config(prefer_summary=True))
    assert items[0]["summary"] == "Some text."


@pytest.mark.parametrize("url, safe", [
    ("https://example.org/post", True),
    ("http://example.org/post", True),
    ("#frag", True),
    ("javascript:alert(1)", False),
    ("java\x00script:alert(1)", False),
    ("data:text/html,<x>1</x>", False),
    ("", False),
])
def test_safe_link(url, safe):
    """Feed links with non-http(s) schemes are disabled."""
    assert safe_link(url) == (url if safe else "#")


def test_summaries_sanitized_once_for_all_outputs(tmp_path):
    """One sanitizer policy at fetch time covers both outputs: unsafe
    markup such as iframes and forms never reaches any item."""
    feed = tmp_path / "evil.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>t</title><link href="https://x.example/"/>'
        '<id>1</id><updated>2026-01-01T00:00:00Z</updated>'
        '<content type="html">'
        '&lt;iframe src="https://evil.example/"&gt;&lt;/iframe&gt;'
        '&lt;form&gt;&lt;button formaction="javascript:x"&gt;b&lt;/button&gt;&lt;/form&gt;'
        'still-ok</content></entry></feed>',
        encoding="utf-8")
    items = fetch_all_items({"feeds": [{"url": str(feed)}]})
    assert "<iframe" not in items[0]["summary"]
    assert "<form" not in items[0]["summary"]
    assert "still-ok" in items[0]["summary"]


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
            {"url": str(REPO / "test-data" / "atom.xml"), "name": "Atom test",
             "icon": "https://example.org/atom-icon.png"},
            {"url": str(REPO / "test-data" / "rss.xml"), "name": "RSS test",
             "resolve_urls": True},
        ],
    }
    config_file = tmp_path / "config.yaml"
    config_file.write_text(yaml.safe_dump(config), encoding="utf-8")

    # cwd in tmp_path so the run cannot depend on the repo layout;
    # PYTHONPATH makes the in-repo package importable without install
    env = {**os.environ, "PYTHONPATH": str(REPO)}
    subprocess.run(
        [sys.executable, "-m", "pyplanet2", str(config_file)],
        cwd=tmp_path, check=True, env=env,
    )

    html_text = (tmp_path / "planet.html").read_text(encoding="utf-8")
    assert "First item title" in html_text
    # feed with an icon configured renders the image, the other the
    # grey placeholder box
    assert "https://example.org/atom-icon.png" in html_text
    assert "icon-placeholder" in html_text

    atom_text = (tmp_path / "atom.xml").read_text(encoding="utf-8")
    ElementTree.fromstring(atom_text)  # raises if not valid XML
    assert "First item title" in atom_text


# --- image cache ---------------------------------------------------------

def img_config(tmp_path, **img_opts):
    images = {"dir": str(tmp_path / "images")}
    images.update(img_opts)
    return {"site": {"site_url": "https://planet.example/"}, "images": images}


def test_localize_downloads_and_rewrites(tmp_path):
    url = "https://img.example/a.png"
    calls = []

    def fetch(u, headers):
        calls.append(u)
        return 200, b"PNGDATA", {"content-type": "image/png", "etag": '"v1"'}

    items = [{"summary": f'<p><img src="{url}"></p>', "icon": url}]
    localize_images(items, img_config(tmp_path), fetcher=fetch)
    assert calls == [url]  # fetched once although used by img and icon
    mapping = items[0]["img_map"]
    assert mapping[url]["atom"].startswith("https://planet.example/")
    assert items[0]["icon"] == mapping[url]["html"]
    html = rewrite_images(items[0]["summary"], mapping, "html")
    assert f'src="{url}"' not in html
    assert f'src={mapping[url]["html"]}' in html.replace('"', "")
    cached = [p for p in (tmp_path / "images").iterdir() if p.suffix == ".png"]
    assert cached and cached[0].read_bytes() == b"PNGDATA"
    assert len(cached[0].stem) == 16  # hash-only file name


def test_localize_skips_fresh_cache(tmp_path):
    url = "https://img.example/a.png"

    def ok(u, headers):
        return 200, b"X", {"content-type": "image/png"}

    localize_images([{"summary": f'<img src="{url}">', "icon": ""}],
                    img_config(tmp_path), fetcher=ok)
    calls = []

    def never(u, headers):
        calls.append(u)
        return 200, b"", {}

    items = [{"summary": f'<img src="{url}">', "icon": ""}]
    localize_images(items, img_config(tmp_path), fetcher=never)
    assert calls == []  # within TTL: no network at all
    assert url not in rewrite_images(items[0]["summary"],
                                     items[0]["img_map"], "html")


def test_localize_revalidates_with_304(tmp_path):
    url = "https://img.example/a.png"

    def ok(u, headers):
        return 200, b"PNG", {"content-type": "image/png", "etag": '"v1"'}

    localize_images([{"summary": f'<img src="{url}">', "icon": ""}],
                    img_config(tmp_path), fetcher=ok)
    seen = []

    def not_modified(u, headers):
        seen.append(dict(headers))
        return 304, b"", {}

    items = [{"summary": f'<img src="{url}">', "icon": ""}]
    localize_images(items, img_config(tmp_path, ttl_days=0), fetcher=not_modified)
    assert seen and seen[0].get("If-None-Match") == '"v1"'
    assert url not in rewrite_images(items[0]["summary"],
                                     items[0]["img_map"], "html")


def test_localize_refuses_unsafe_images(tmp_path):
    cases = {
        "https://x.example/a.png": (200, b"<html/>", {"content-type": "text/html"}),
        "https://x.example/b.svg": (200, b"<svg/>", {"content-type": "image/svg+xml"}),
        "https://x.example/c.png": (404, b"", {}),
    }

    def fetch(u, headers):
        return cases[u]

    summary = "".join(f'<img src="{u}">' for u in sorted(cases))
    items = [{"summary": summary, "icon": ""}]
    localize_images(items, img_config(tmp_path), fetcher=fetch)
    assert not items[0].get("img_map")
    for u in cases:  # originals are kept when caching fails
        assert f'src="{u}"' in items[0]["summary"]


def test_fetcher_refuses_private_hosts():
    fetch = imagecache.make_urllib_fetcher(timeout=1)
    for url in ("http://localhost/a.png", "http://192.168.4.1/a.png",
                "ftp://example.org/a.png"):
        with pytest.raises(ValueError):
            fetch(url, {})