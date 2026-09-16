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

from pyplanet2.core import (TEMPLATE_DIR, fetch_all_items,
                                 generate_atom_feed, generate_html_view,
                                 make_urls_absolute, sanitize_html, safe_link,
                                validate_config)
from pyplanet2 import core, imagecache
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


def test_author_only_when_configured(tmp_path):
    """An unset author stays empty (the HTML then omits it) instead of
    defaulting to the feed name."""
    base = {"url": str(REPO / "test-data" / "atom.xml")}
    unset = fetch_all_items({"feeds": [dict(base)]})
    assert unset[0]["author"] == ""
    configured = fetch_all_items({"feeds": [{**base, "author": "Jane"}]})
    assert configured[0]["author"] == "Jane"


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
    ("mailto:a@b.example", True),
    ("javascript:1", False),
    ("javascript:alert(1)", False),
    ("java\tscript:2", False),
    (" javascript:1", False),
    ("java\x00script:alert(1)", False),
    ("data:text/html,<x>1</x>", False),
    ("", False),
])
def test_safe_link(url, safe):
    """Feed links pass only with http(s), mailto, or as relative URLs."""
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


@pytest.mark.parametrize("shape", [
    "javascript:1",
    "javascript:alert(1)",
    "java\tscript:2",
    " javascript:1",
    "jAvAsCrIpT:1",
    "java&#9;script:2",
    "JaVa\nScRiPt:1",
    "data:text/html,<x>1</x>",
    "vbscript:1",
    "file:///etc/passwd",
])
def test_summary_url_scheme_allowlist(shape):
    """bleach's protocol check is fail-open for a few malformed shapes
    ("javascript:1", "java[tab]script:2", ...); the url_scheme_filter
    must strip every href/src whose scheme is not allow-listed."""
    assert "href" not in sanitize_html(f'<a href="{shape}">c</a>')
    assert "src" not in sanitize_html(f'<img src="{shape}">')


def test_summary_url_allowlist_keeps_good_urls():
    out = sanitize_html(
        '<a href="https://ok.example/a?x=1#f">l</a>'
        '<a href="mailto:a@b.example">m</a>'
        '<a href="/rel">r</a><a href="#frag">f</a>'
        '<img src="../img.png" alt="i">')
    assert "https://ok.example/a?x=1#f" in out
    assert "mailto:a@b.example" in out
    assert 'href="/rel"' in out and 'href="#frag"' in out
    assert 'src="../img.png"' in out


def test_feed_urls_never_executable_in_outputs(tmp_path):
    """End-to-end: nasty feed URLs never reach either output as a
    navigable javascript: attribute (browser-equivalent flattening)."""
    import html as html_lib
    import re
    feed = tmp_path / "evil.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>bad link</title><link href="javascript:1"/>'
        '<id>1</id><updated>2026-01-01T00:00:00Z</updated></entry>'
        '<entry><title>bad summary</title>'
        '<link href="https://ok.example/e2"/>'
        '<id>2</id><updated>2026-01-01T00:00:00Z</updated>'
        '<content type="html">'
        '&lt;a href="java&amp;#9;script:2"&gt;a&lt;/a&gt;'
        '&lt;img src=" javascript:1"&gt;'
        '&lt;a href="https://ok.example/x"&gt;ok&lt;/a&gt;'
        '</content></entry></feed>',
        encoding="utf-8")
    config = {
        "site": {"title": "T", "site_url": "https://p.example/",
                 "atom_feed_url": "https://p.example/atom.xml"},
        "output": {"atom_feed": str(tmp_path / "atom.xml"),
                   "html_view": str(tmp_path / "planet.html")},
        "limits": {"max_feed_items": 50, "html_view_limit": 50},
        "feeds": [{"url": str(feed)}],
    }
    items = fetch_all_items(config)
    generate_atom_feed(items, config["output"]["atom_feed"], config)
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)
    pattern = re.compile(r"(?:href|src)\s*=\s*[\"'][^\"']*javascript:", re.I)
    for out in (config["output"]["html_view"], config["output"]["atom_feed"]):
        text = html_lib.unescape(Path(out).read_text(encoding="utf-8"))
        flat = text.translate(str.maketrans("", "", "\\t\\n\\r"))
        assert not pattern.search(flat), out


def test_config_validation_reports_missing_keys(tmp_path, capsys):
    """A config with missing required keys fails with one clear message
    instead of a bare KeyError from deep inside a generator."""
    with pytest.raises(SystemExit):
        validate_config({"site": {"title": "x"}})
    err = capsys.readouterr().err
    assert "site.site_url" in err and "feeds" in err
    assert "config is missing required key(s)" in err
    # the sample shape from the README passes untouched
    validate_config({
        "site": {"title": "t", "site_url": "u", "atom_feed_url": "a"},
        "output": {"atom_feed": "x", "html_view": "h"},
        "limits": {"max_feed_items": 1, "html_view_limit": 1},
        "feeds": [{"url": "u"}],
    })


def test_missing_local_feed_is_fatal(tmp_path, capsys):
    """A configured local feed file that does not exist stops the build
    with a clear message instead of silently contributing nothing."""
    with pytest.raises(SystemExit):
        fetch_all_items({"feeds": [{"url": str(tmp_path / "nope.xml")}]})
    assert "local feed file not found" in capsys.readouterr().err


def test_corrupt_local_feed_is_fatal(tmp_path, capsys):
    corrupt = tmp_path / "bad.xml"
    corrupt.write_text("hello, definitely not a feed")
    with pytest.raises(SystemExit):
        fetch_all_items({"feeds": [{"url": str(corrupt)}]})
    assert "local feed unreadable" in capsys.readouterr().err


def test_remote_feed_failure_warns_and_continues(tmp_path, monkeypatch, capsys):
    """An unreachable remote feed is skipped with a warning (annotated
    in Actions runs) while the other feeds still contribute."""
    import feedparser as feedparser_mod

    class Dead:
        entries = []
        bozo = True
        bozo_exception = OSError("<urlopen error simulated offline>")

    real_parse = feedparser_mod.parse

    def fake_parse(url, **kwargs):
        if str(url).startswith("http"):
            return Dead()
        return real_parse(url, **kwargs)

    monkeypatch.setattr(core.feedparser, "parse", fake_parse)
    monkeypatch.setenv("GITHUB_ACTIONS", "true")
    items = fetch_all_items({"feeds": [
        {"url": "http://dead.example/feed.xml"},
        {"url": str(REPO / "test-data" / "atom.xml")},
    ]})
    assert items, "the working local feed must still contribute"
    out = capsys.readouterr().out
    assert "WARNING: feed skipped" in out
    assert "::warning title=pyplanet2::" in out


def test_valid_empty_feed_is_silent(tmp_path, capsys):
    empty = tmp_path / "empty.xml"
    empty.write_text('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')
    assert fetch_all_items({"feeds": [{"url": str(empty)}]}) == []
    assert "WARNING" not in capsys.readouterr().out


def test_max_posts_per_feed_caps_html_only(tmp_path):
    """The HTML page shows at most max_posts_per_feed posts from one
    feed (the newest ones); the Atom feed keeps everything."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    entries = "".join(
        f'<entry><title>Big {i}</title>'
        f'<link href="https://big.example/{i}"/><id>{i}</id>'
        f'<updated>{(now - timedelta(days=i)).isoformat()}</updated></entry>'
        for i in range(3))
    big = tmp_path / "big.xml"
    big.write_text('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
                   f'{entries}</feed>', encoding="utf-8")
    config = {
        "site": {"title": "T", "site_url": "https://p.example/",
                 "atom_feed_url": "https://p.example/atom.xml"},
        "output": {"atom_feed": str(tmp_path / "atom.xml"),
                   "html_view": str(tmp_path / "page.html")},
        "limits": {"max_feed_items": 100, "html_view_limit": 50,
                   "max_posts_per_feed": 1},
        "feeds": [{"url": str(big)},
                  {"url": str(REPO / "test-data" / "atom.xml")}],
    }
    items = fetch_all_items(config)
    assert len(items) == 4
    generate_atom_feed(items, config["output"]["atom_feed"], config)
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    feed = Path(config["output"]["atom_feed"]).read_text(encoding="utf-8")
    assert "Big 0" in page and "Big 1" not in page and "Big 2" not in page
    assert page.count("Atom-Powered Robots") == 1
    # each of the 3 entries appears in <link> and <id>: uncapped Atom feed
    assert feed.count("big.example") == 6
    assert "Atom-Powered Robots" in feed


def test_max_age_days_drops_old_posts_everywhere(tmp_path):
    """max_age_days trims the shared pool: too-old posts vanish from
    both outputs, while unset/0 keeps every age."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    feed = tmp_path / "mixed.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        f'<entry><title>Fresh</title><link href="https://x/1"/><id>1</id>'
        f'<updated>{(now - timedelta(days=1)).isoformat()}</updated></entry>'
        f'<entry><title>Ancient</title><link href="https://x/2"/><id>2</id>'
        f'<updated>{(now - timedelta(days=365)).isoformat()}</updated></entry>'
        '</feed>', encoding="utf-8")
    base = {
        "site": {"title": "T", "site_url": "https://p.example/",
                 "atom_feed_url": "https://p.example/atom.xml"},
        "output": {"atom_feed": str(tmp_path / "atom.xml"),
                   "html_view": str(tmp_path / "page.html")},
        "feeds": [{"url": str(feed)}],
    }
    old = dict(base, limits={"max_feed_items": 100, "html_view_limit": 50,
                             "max_age_days": 30})
    assert [i["title"] for i in fetch_all_items(old)] == ["Fresh"]
    unlimited = dict(base, limits={"max_feed_items": 100, "html_view_limit": 50})
    assert len(fetch_all_items(unlimited)) == 2


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
    # no feed configures an author, so the meta line omits it entirely
    assert "Author:" not in html_text

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