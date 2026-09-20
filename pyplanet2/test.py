"""Tests for pyplanet2.

Run from the repository root with:  pytest

All tests are offline: they only read the sample feeds in test-data/.
"""
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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
            "feed": str(REPO / "test-data" / "rss.xml"),
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


def test_feed_title_is_the_local_name_only(tmp_path):
    """The displayed feed title always comes from the config's name --
    a feed's own remote <title> is never shown, and the old author key
    is gone entirely."""
    items = fetch_all_items({"feeds": [
        {"feed": str(REPO / "test-data" / "atom.xml"), "name": "My Blog"}]})
    assert items[0]["feed_title"] == "My Blog"
    assert "author" not in items[0]


def make_atom_config(**feed_opts):
    """Config for fetch_all_items() over the Atom sample feed."""
    feed = {"feed": str(REPO / "test-data" / "atom.xml"), "name": "Atom test"}
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
    items = fetch_all_items({"feeds": [{"feed": str(feed)}]})
    assert "<iframe" not in items[0]["summary"]
    assert "<form" not in items[0]["summary"]
    assert "still-ok" in items[0]["summary"]


LOSS_CASES = [
    ("<video src='v.mp4'>play</video>", ["video"]),
    ("<iframe src='https://v.example/x'></iframe>", ["iframe"]),
    ("<svg width='4'><circle/></svg>", ["svg"]),
    ("<form><input/></form>", ["form", "input"]),
    ("plain <strong>text</strong> here", []),
    ("<figure><figcaption>caption</figcaption></figure>", []),
]


@pytest.mark.parametrize("markup, flagged", LOSS_CASES)
def test_removed_content_flag(tmp_path, markup, flagged):
    """removed_content lists exactly the elements whose content the
    sanitizer loses; text-carrying markup yields an empty list."""
    escaped = (markup.replace("&", "&amp;").replace("<", "&lt;")
               .replace(">", "&gt;"))
    feed = tmp_path / "loss.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>t</title><link href="https://x.example/"/>'
        '<id>1</id><updated>2026-01-01T00:00:00Z</updated>'
        f'<content type="html">{escaped}</content></entry></feed>',
        encoding="utf-8")
    items = fetch_all_items({"feeds": [{"feed": str(feed)}]})
    assert items[0]["removed_content"] == flagged


def test_script_style_bodies_dropped(tmp_path):
    """bleach keeps the text of stripped tags, so script and style
    bodies are removed wholesale instead of leaking as visible code."""
    feed = tmp_path / "junk.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>t</title><link href="https://x.example/"/>'
        '<id>1</id><updated>2026-01-01T00:00:00Z</updated>'
        '<content type="html">'
        '&lt;script&gt;alert(1)&lt;/script&gt; visible\n'
        '&lt;style&gt;.x{color:red}&lt;/style&gt; text</content>'
        '</entry></feed>', encoding="utf-8")
    summary = fetch_all_items({"feeds": [{"feed": str(feed)}]})[0]["summary"]
    assert "alert" not in summary and "color:red" not in summary
    assert "visible" in summary and "text" in summary


def test_removed_content_note_rendered(tmp_path):
    """A post whose media was dropped gets the note under its title;
    ordinary posts render without one."""
    feed = tmp_path / "media.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>V</title><link href="https://x.example/v"/>'
        '<id>1</id><updated>2026-01-01T00:00:00Z</updated>'
        '<content type="html">&lt;video src="v.mp4"&gt;watch&lt;/video&gt;'
        '</content></entry></feed>', encoding="utf-8")
    config = theming_config(tmp_path)
    config["feeds"] = [{"feed": str(feed), "name": "V"}]
    generate_html_view(fetch_all_items(config),
                       config["output"]["html_view"], TEMPLATE_DIR, config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    assert 'class="content-note"' in page
    assert "consider seeing the original post" in page
    assert "(video)" in page
    plain_view = str(tmp_path / "plain.html")
    config2 = theming_config(tmp_path)
    config2["output"] = dict(config2["output"], html_view=plain_view)
    generate_html_view(fetch_all_items(config2),
                       plain_view, TEMPLATE_DIR, config2)
    page2 = Path(plain_view).read_text(encoding="utf-8")
    assert 'class="content-note"' not in page2


def test_removed_content_note_in_atom_feed(tmp_path):
    """The aggregated Atom feed carries the same warning, prepended to
    the entry, since many readers show only the feed."""
    feed = tmp_path / "media.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>V</title><link href="https://x.example/v"/>'
        '<id>1</id><updated>2026-01-01T00:00:00Z</updated>'
        '<content type="html">&lt;p&gt;body&lt;/p&gt;'
        '&lt;video src="v.mp4"&gt;&lt;/video&gt;</content>'
        '</entry></feed>', encoding="utf-8")
    config = theming_config(tmp_path)
    config["feeds"] = [{"feed": str(feed), "name": "V"}]
    generate_atom_feed(fetch_all_items(config),
                       config["output"]["atom_feed"], config)
    xml = Path(config["output"]["atom_feed"]).read_text(encoding="utf-8")
    assert "consider seeing the original post" in xml
    assert "(video)" in xml
    assert xml.index("consider seeing") < xml.index("body")  # leads entry


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
        "feeds": [{"feed": str(feed)}],
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
        "feeds": [{"feed": "u", "name": "n"}],
    })


def test_missing_local_feed_is_fatal(tmp_path, capsys):
    """A configured local feed file that does not exist stops the build
    with a clear message instead of silently contributing nothing."""
    with pytest.raises(SystemExit):
        fetch_all_items({"feeds": [{"feed": str(tmp_path / "nope.xml")}]})
    assert "local feed file not found" in capsys.readouterr().err


def test_corrupt_local_feed_is_fatal(tmp_path, capsys):
    corrupt = tmp_path / "bad.xml"
    corrupt.write_text("hello, definitely not a feed")
    with pytest.raises(SystemExit):
        fetch_all_items({"feeds": [{"feed": str(corrupt)}]})
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
        {"feed": "http://dead.example/feed.xml"},
        {"feed": str(REPO / "test-data" / "atom.xml")},
    ]})
    assert items, "the working local feed must still contribute"
    out = capsys.readouterr().out
    assert "WARNING: feed skipped" in out
    assert "::warning title=pyplanet2::" in out


def test_valid_empty_feed_is_silent(tmp_path, capsys):
    empty = tmp_path / "empty.xml"
    empty.write_text('<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom"></feed>')
    assert fetch_all_items({"feeds": [{"feed": str(empty)}]}) == []
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
        "feeds": [{"feed": str(big)},
                  {"feed": str(REPO / "test-data" / "atom.xml")}],
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
        "feeds": [{"feed": str(feed)}],
    }
    old = dict(base, limits={"max_feed_items": 100, "html_view_limit": 50,
                             "max_age_days": 30})
    assert [i["title"] for i in fetch_all_items(old)] == ["Fresh"]
    unlimited = dict(base, limits={"max_feed_items": 100, "html_view_limit": 50})
    assert len(fetch_all_items(unlimited)) == 2


def theming_config(tmp_path):
    """A full valid config over the Atom test feed for template tests."""
    return {
        "site": {"title": "Theme Planet", "site_url": "https://p.example/",
                 "atom_feed_url": "https://p.example/atom.xml"},
        "output": {"atom_feed": str(tmp_path / "atom.xml"),
                   "html_view": str(tmp_path / "page.html")},
        "limits": {"max_feed_items": 100, "html_view_limit": 50},
        "feeds": [{"feed": str(REPO / "test-data" / "atom.xml"),
                   "name": "Atom test"}],
    }


def test_feed_name_required_and_template_check(tmp_path, capsys):
    """A feed without a local name, or a paths.template typo, fails
    validation with a clear message before any fetching starts."""
    config = theming_config(tmp_path)
    del config["feeds"][0]["name"]
    with pytest.raises(SystemExit):
        validate_config(config)
    err = capsys.readouterr().err
    assert "feeds[0].name" in err
    config["feeds"][0]["name"] = "n"
    config["paths"] = {"template": "nope.html"}
    with pytest.raises(SystemExit):
        validate_config(config)
    err = capsys.readouterr().err
    assert "nope.html" in err and "not found" in err


def test_theme_extends_base_blocks(tmp_path):
    """A user template in paths.template_dir extends the bundled base
    and overrides single blocks; everything else comes from the base."""
    themes = tmp_path / "themes"
    themes.mkdir()
    (themes / "custom.html").write_text(
        '{% extends "planet.html" %}\n'
        '{% block footer %}<footer class="mine">Handmade</footer>{% endblock %}\n',
        encoding="utf-8")
    config = theming_config(tmp_path)
    config["paths"] = {"template_dir": str(themes), "template": "custom.html"}
    items = fetch_all_items(config)
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    assert "Handmade" in page
    assert "pyplanet2 blog aggregator" not in page  # base footer replaced
    assert "Theme Planet" in page                   # base header intact
    assert "Atom-Powered Robots" in page            # posts intact


def test_theme_sidebar_lists_configured_feeds(tmp_path):
    """The feeds context carries every configured feed with its local
    name for theme blocks such as a sidebar -- feeds without posts
    included."""
    themes = tmp_path / "themes"
    themes.mkdir()
    (themes / "side.html").write_text(
        '{% extends "planet.html" %}\n'
        '{% block sidebar %}<aside>{% for f in feeds %}'
        '<a href="{{ f.site }}">{{ f.title }}</a>{% endfor %}</aside>'
        '{% endblock %}\n', encoding="utf-8")
    (tmp_path / "empty.xml").write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '</feed>', encoding="utf-8")
    config = theming_config(tmp_path)
    config["feeds"].append({"feed": str(tmp_path / "empty.xml"),
                            "name": "Silent blog",
                            "site": "https://s.example/"})
    config["paths"] = {"template_dir": str(themes), "template": "side.html"}
    items = fetch_all_items(config)
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    assert page.count("<aside>") == 1
    assert ">Atom test</a>" in page and ">Silent blog</a>" in page


def test_theme_replaces_base_completely(tmp_path):
    """Without extends a template fully replaces the base output."""
    themes = tmp_path / "themes"
    themes.mkdir()
    (themes / "plain.html").write_text(
        'REPLACED: {{ site_title }} / {{ posts|length }} posts / '
        '{% for f in feeds %}{{ f.title }};{% endfor %}', encoding="utf-8")
    config = theming_config(tmp_path)
    config["paths"] = {"template_dir": str(themes), "template": "plain.html"}
    items = fetch_all_items(config)
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    assert page == f"REPLACED: Theme Planet / {len(items)} posts / Atom test;"


def test_default_sidebar_links_feeds(tmp_path):
    """The base template's default sidebar lists every feed: the name
    links to the site and a separate "feed" link goes to the feed."""
    config = theming_config(tmp_path)
    config["feeds"].append({"feed": str(REPO / "test-data" / "rss.xml"),
                            "name": "RSS test",
                            "site": "https://blog.example.org/"})
    items = fetch_all_items(config)
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    assert page.count("feeds-sidebar") >= 1  # aside renders by default
    assert 'href="https://blog.example.org/">RSS test</a>' in page
    assert '>RSS test</a>' in page and 'feed-ref' in page
    assert f'href="{config["feeds"][0]["feed"]}">' in page  # name link falls back to url


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
            {"feed": str(REPO / "test-data" / "atom.xml"), "name": "Atom test",
             "icon": "https://example.org/atom-icon.png"},
            {"feed": str(REPO / "test-data" / "rss.xml"), "name": "RSS test",
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
    images = {"dir": str(tmp_path / "images-cached")}
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
    cached = [p for p in (tmp_path / "images-cached").iterdir()
            if p.suffix == ".png"]
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
    """Images the cache cannot take (a non-image type, a missing file)
    keep their original url.  svg is deliberately NOT in this list: it
    gets dropped, because it must never be fetched from either place."""
    cases = {
        "https://x.example/a.png": (200, b"<html/>", {"content-type": "text/html"}),
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


def test_large_images_dropped_not_remote(tmp_path):
    """Images over the size cap are removed from the post, flagged in
    removed_content, and never left pointing at the remote host."""
    from pyplanet2.imagecache import ImageTooLarge
    huge = "https://img.example/huge.png"
    fine = "https://img.example/ok.png"

    def fetch(u, headers):
        if u == huge:
            raise ImageTooLarge("image exceeds 10485760 bytes: " + u)
        return 200, b"PNGDATA", {"content-type": "image/png"}

    items = [{"summary": f'<p>t</p><img src="{huge}" alt="x">'
                          f'<img src="{fine}">',
              "icon": huge, "removed_content": ["video"]}]
    localize_images(items, img_config(tmp_path), fetcher=fetch)
    assert huge not in items[0]["summary"]
    assert items[0]["icon"] == ""
    assert items[0]["removed_content"] == ["large image", "video"]
    # the fine one is cached and mapped for the generators to rewrite
    assert fine in items[0]["img_map"]
    assert items[0]["img_map"][fine]["html"].endswith(".png")
    assert (tmp_path / "images-cached").is_dir()  # the fine one was cached


SVG_BODY = b'<svg xmlns="http://www.w3.org/2000/svg"><script>steal()</script></svg>'


def svg_fetcher(u, headers):
    """Any url: an svg, which is never cacheable."""
    return 200, SVG_BODY, {"content-type": "image/svg+xml"}


def test_remote_svg_dropped_not_remote(tmp_path):
    """An svg is neither cached nor left remote: caching it could put a
    scriptable document on the site's own origin, keeping it remote would
    leak the reader's requests to the feed host, so the img is removed
    from the post and flagged instead -- the treatment oversized images
    already get."""
    svg = "https://img.example/x.svg"
    fine = "https://img.example/ok.png"

    def fetch(u, headers):
        if u == svg:
            return 200, SVG_BODY, {"content-type": "image/svg+xml"}
        return 200, b"PNGDATA", {"content-type": "image/png"}

    items = [{"summary": f'<p>t</p><img src="{svg}" alt="x"><img src="{fine}">',
              "icon": "", "removed_content": ["video"]}]
    localize_images(items, img_config(tmp_path), fetcher=fetch)
    assert svg not in items[0]["summary"]
    assert fine in items[0]["summary"]  # only the svg went
    assert items[0]["removed_content"] == ["SVG image", "video"]
    assert svg not in items[0]["img_map"]
    assert items[0]["img_map"][fine]["html"].endswith(".png")
    cache = tmp_path / "images-cached"
    assert not [p for p in cache.iterdir() if p.suffix == ".svg"]
    assert svg not in json.loads((cache / "index.json").read_text("utf-8"))


@pytest.mark.parametrize("shape,ctype", [
    ("plain", "image/svg+xml"),
    ("params", "IMAGE/SVG+XML; charset=utf-8"),
    ("padded", "  image/svg+xml ;q=0.9"),
])
def test_svg_dropped_whatever_the_header_shape(tmp_path, shape, ctype):
    """The decision reads the normalized content type, so case, padding
    or a parameter cannot smuggle an svg into the cache or the output."""
    svg = "https://img.example/x.svg"
    items = [{"summary": f'<img src="{svg}">', "icon": ""}]
    localize_images(items, img_config(tmp_path / shape),
                    fetcher=lambda u, h: (200, SVG_BODY, {"content-type": ctype}))
    assert items[0]["summary"] == ""
    assert items[0]["removed_content"] == ["SVG image"]


def test_svg_feed_icon_falls_back_to_placeholder(tmp_path):
    """A feed icon that must not stay remote is dropped, so the HTML view
    shows the grey placeholder box instead of a remote svg."""
    svg = "https://img.example/icon.svg"
    items = [{"summary": "<p>t</p>", "icon": svg}]
    localize_images(items, img_config(tmp_path), fetcher=svg_fetcher)
    assert items[0]["icon"] == ""
    assert items[0]["removed_content"] == ["SVG image"]


def test_svg_note_in_both_output_views(tmp_path):
    """The dropped svg is reported in the HTML view and in the aggregated
    Atom feed, with the same note that covers video and oversized ones."""
    feed = tmp_path / "svged.xml"
    feed.write_text(
        '<?xml version="1.0"?><feed xmlns="http://www.w3.org/2005/Atom">'
        '<entry><title>S</title><link href="https://x.example/s"/>'
        '<id>1</id><updated>2026-01-01T00:00:00Z</updated>'
        '<content type="html">&lt;p&gt;body&lt;/p&gt;'
        '&lt;img src="https://img.example/x.svg"&gt;</content>'
        '</entry></feed>', encoding="utf-8")
    config = theming_config(tmp_path)
    config["feeds"] = [{"feed": str(feed), "name": "S"}]
    items = fetch_all_items(config)
    localize_images(items, img_config(tmp_path), fetcher=svg_fetcher)
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)
    generate_atom_feed(items, config["output"]["atom_feed"], config)
    for out in (config["output"]["html_view"], config["output"]["atom_feed"]):
        text = Path(out).read_text(encoding="utf-8")
        assert "SVG image" in text
        assert "consider seeing the original post" in text
        assert "img.example/x.svg" not in text  # not even left remote


def test_favicon_renders_link(tmp_path):
    """Favicon: unset renders no link tag; a local path appears verbatim."""
    config = theming_config(tmp_path)
    generate_html_view([], config["output"]["html_view"], TEMPLATE_DIR,
                       config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    assert 'rel="icon"' not in page
    config["output"]["favicon"] = "my-icon.png"
    generate_html_view([], config["output"]["html_view"], TEMPLATE_DIR,
                       config)
    page = Path(config["output"]["html_view"]).read_text(encoding="utf-8")
    assert '<link rel="icon" href="my-icon.png">' in page


def test_site_image_caching(tmp_path):
    """localize_site_image: local verbatim, remote cached, oversized
    dropped, unreachable keeps its URL."""
    from pyplanet2.imagecache import localize_site_image, ImageTooLarge

    def ok(u, headers):
        return 200, b"PNGDATA", {"content-type": "image/png"}

    got = localize_site_image("https://img.example/icon.png",
                              img_config(tmp_path), fetcher=ok)
    assert got.endswith(".png") and Path(got).is_file()

    def huge(u, headers):
        raise ImageTooLarge("oversized")

    assert localize_site_image("https://img.example/big.png",
                               img_config(tmp_path),
                               fetcher=huge) == ""

    def boom(u, headers):
        raise OSError("network down")

    keep = "https://img.example/down.png"
    assert localize_site_image(keep, img_config(tmp_path),
                               fetcher=boom) == keep
    # an svg has no content note to flag it, so it is dropped silently
    assert localize_site_image("https://img.example/icon.svg",
                               img_config(tmp_path),
                               fetcher=svg_fetcher) == ""
    assert localize_site_image("local.ico",
                               img_config(tmp_path)) == "local.ico"


def test_poisoned_cache_index_non_raster_refused(tmp_path):
    """The cache index is a trusted input, but naming a scriptable file
    there must still never become a same-origin reference: _trusted_name
    limits entries to the extensions the writer itself can produce, and
    refusing heals the entry because the url gets fetched again."""
    cache = tmp_path / "images-cached"
    cache.mkdir()
    for name in ("deadbeefdeadbeef.svg", "cafebabecafebabe.html"):
        (cache / name).write_bytes(SVG_BODY)
    fresh = datetime.now(timezone.utc).isoformat(timespec="seconds")
    urls = {"https://img.example/a.png": "deadbeefdeadbeef.svg",
            "https://img.example/b.png": "cafebabecafebabe.html"}
    (cache / "index.json").write_text(
        json.dumps({u: {"file": f, "fetched_at": fresh}
                    for u, f in urls.items()}), encoding="utf-8")

    asked = []

    def fetch(u, headers):
        asked.append(u)
        return 200, b"PNGDATA", {"content-type": "image/png"}

    summary = "".join(f'<img src="{u}">' for u in sorted(urls))
    items = [{"summary": summary, "icon": ""}]
    mapping = localize_images(items, img_config(tmp_path), fetcher=fetch)
    assert sorted(asked) == sorted(urls)  # refused entries went to the network
    assert all(v["html"].endswith(".png") for v in mapping.values())
    for bad in (".svg", ".html"):
        assert bad not in rewrite_images(summary, mapping, "html")
    saved = json.loads((cache / "index.json").read_text("utf-8"))
    assert all(v["file"].endswith(".png") for v in saved.values())


def test_trusted_name_matches_only_the_writers_output():
    """What the index may name is exactly what the writer can produce, so
    no legitimate cache is ever invalidated by the check."""
    for ext in imagecache.CACHE_EXTS:
        assert imagecache._trusted_name("0123456789abcdef." + ext)
    for name in ("0123456789abcdef.svg", "0123456789abcdef.html",
                 "0123456789abcdef.htm", "0123456789abcdef.PNG",
                 "z123456789abcdef.png", "../../etc/passwd", ""):
        assert not imagecache._trusted_name(name)
