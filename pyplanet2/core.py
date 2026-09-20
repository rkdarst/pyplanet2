#!/usr/bin/env python3
"""
Blog aggregator that combines RSS feeds into:
1. An aggregated Atom feed (atom.xml)
2. A static HTML view of the last 10 posts (planet.html)

Configuration is loaded from a YAML file (config.yaml by default,
or pass a path as the first argument).
"""
import argparse
import base64
import html
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import bleach
import feedparser
import yaml
from feedgenerator import Atom1Feed
from jinja2 import Environment, FileSystemLoader

from .imagecache import (localize_images, localize_site_image, prune_cache,
                         rewrite_images)

def load_config(path):
    """Load configuration from a YAML file."""
    config_file = Path(path)
    if not config_file.exists():
        print(f"ERROR: config file not found: {config_file}", file=sys.stderr)
        sys.exit(1)
    with open(config_file, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"

# Keys every config must carry; dotted paths mirror how they are read.
REQUIRED_KEYS = (
    "site.title", "site.site_url", "site.atom_feed_url",
    "output.atom_feed", "output.html_view",
    "limits.max_feed_items", "limits.html_view_limit",
    "feeds",
)


def validate_config(config):
    """Exit with one clear message listing every missing required key.

    Without this, a config typo surfaces as a bare KeyError deep inside
    a generator; the README sample config documents the full shape.
    """
    missing = []
    for dotted in REQUIRED_KEYS:
        node = config
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                missing.append(dotted)
                break
            node = node[part]
    if isinstance(config.get("feeds"), list):
        for i, feed in enumerate(config["feeds"]):
            if not isinstance(feed, dict):
                missing.append(f"feeds[{i}]")
                continue
            for key in ("feed", "name"):
                if key not in feed:
                    missing.append(f"feeds[{i}].{key}")
    if missing:
        print("ERROR: config is missing required key(s): "
              + ", ".join(missing), file=sys.stderr)
        print("See the README sample config for the full shape.",
              file=sys.stderr)
        sys.exit(1)
    # Fail before fetching, not mid-render, on a template typo.
    paths = config.get("paths") or {}
    template = paths.get("template", "planet.html")
    search = ([Path(paths["template_dir"])] if paths.get("template_dir")
              else []) + [TEMPLATE_DIR]
    if not any((d / template).is_file() for d in search):
        print(f"ERROR: HTML template '{template}' not found (looked in: "
              + ", ".join(str(d) for d in search) + ")", file=sys.stderr)
        sys.exit(1)
    return config


def parse_dt(entry):
    """Parse publication or update date from feed entry."""
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if getattr(entry, "updated_parsed", None):
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


# URL attribute values, as re-serialized by feedparser's HTML sanitizer
# (attributes always come out double-quoted there; both quote styles are
# matched defensively).
REL_URL_ATTR_RE = re.compile(r"""\b(src|href)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _resolve_url(url, base_url):
    """Resolve a single URL against base_url, leaving absolute ones alone."""
    url = url.strip()
    if not url or url.startswith("#") or urlparse(url).scheme:
        return url
    return urljoin(base_url, url)


def make_urls_absolute(html_text, base_url):
    """Rewrite relative src/href URLs in feed HTML to absolute ones.

    URLs are resolved against base_url (the feed item's own link, or the
    feed url when an item carries none), so embedded images and links
    still work once shown on the aggregated page.  Absolute URLs and
    plain #anchors are left untouched.  fetch_all_items() applies this to
    every feed: a relative URL cannot survive on a planet page.
    """
    if not html_text or not base_url or base_url == "#":
        return html_text

    def replace(match):
        quoted = match.group(2)
        value = quoted if quoted is not None else match.group(3)
        quote = '"' if quoted is not None else "'"
        return f"{match.group(1)}={quote}{_resolve_url(value, base_url)}{quote}"

    return REL_URL_ATTR_RE.sub(replace, html_text)


def _item_base(link, feed_base):
    """Base for resolving the URLs inside one item: its own link, or the
    feed document when the entry carries no usable link.

    Neither counts when it is not an address at all: a feed given as a
    local file path has no authority to resolve against, and inventing
    one would rewrite the markup on a guess, so its URLs are left
    exactly as written.
    """
    base = feed_base if link == "#" else link
    return base if urlparse(base).scheme else ""


# URL schemes allowed in feed-supplied href/src attributes and in entry
# links.  The empty scheme covers relative URLs and #fragments; mailto
# preserves bleach's long-standing default.
SAFE_URL_SCHEMES = ("", "http", "https", "mailto")


def _browser_url(url):
    """Return url as browsers will parse it: they drop NUL bytes and
    tab/newline/CR characters from URLs before resolving them (and
    trim surrounding space), so a scheme check must look at exactly
    this form.  XML cannot carry NUL bytes, making that part
    defense-in-depth."""
    url = html.unescape(str(url))  # attribute entities arrive raw here
    for ch in (chr(0), chr(9), chr(10), chr(13)):
        url = url.replace(ch, "")
    return url.strip()


def _url_is_safe(url):
    """True when the browser-parsed url has a SAFE_URL_SCHEMES scheme."""
    return urlparse(_browser_url(url)).scheme.lower() in SAFE_URL_SCHEMES


def url_scheme_filter(source):
    """bleach/html5lib token filter dropping href/src attributes whose
    scheme is not allowed.

    bleach's built-in protocol check only strips URLs its parser
    succeeds in parsing; malformed shapes such as "java[tab]script:2"
    or "javascript:1" survive it fail-open, so the allow-list is
    enforced here over every attribute that reaches the output.
    """
    for token in source:
        if token["type"] in ("StartTag", "EmptyTag"):
            for key, value in list(token["data"].items()):
                if key[1] in ("href", "src") and not _url_is_safe(value):
                    del token["data"][key]
        yield token


def safe_link(url):
    """Return url, or "#" when its scheme is unsafe.

    Only post summaries pass through the sanitizer and its
    url_scheme_filter, so links taken straight from feeds are checked
    here against the same policy: a malicious feed could otherwise
    plant a clickable javascript: link, which the templates' HTML
    escaping would happily preserve.
    """
    url = _browser_url(url)
    return url if url and _url_is_safe(url) else "#"


ALLOWED_TAGS = [
    'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'small',
    'a', 'ul', 'ol', 'li',
    'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
    'blockquote', 'pre', 'code', 'img',
    'div', 'span', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td',
]

ALLOWED_ATTRIBUTES = {
    'a': ['href', 'title', 'rel'],
    'img': ['src', 'alt', 'title', 'width', 'height'],
}

# bleach.clean() has no filters hook, so one Cleaner carries the
# url_scheme_filter bolted in after bleach's own sanitizer.
_CLEANER = bleach.Cleaner(
    tags=ALLOWED_TAGS,
    attributes=ALLOWED_ATTRIBUTES,
    strip=True,
    filters=[url_scheme_filter],
)



# bleach keeps the inner text of stripped tags, so script/style bodies
# (JS and CSS source, never readable prose) are dropped wholesale
# before the cleaner runs.
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b.*?</\1>", re.I | re.S)

# Elements whose content is lost, not merely re-rendered, when the
# cleaner drops them: readers get a note instead of a silent hole.
CONTENT_LOSS_TAGS = {"iframe", "video", "audio", "embed", "object",
                     "applet", "canvas", "svg", "math", "form",
                     "input", "button", "select"}


class _LossScanner(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.found = set()

    def handle_starttag(self, tag, attrs):
        if tag in CONTENT_LOSS_TAGS:
            self.found.add(tag)


def lost_content_tags(html_text):
    """The sorted names of elements the sanitizer will drop whole
    (embedded media, widgets) from raw feed HTML; drives the "content
    not shown" note in both output views."""
    scanner = _LossScanner()
    try:
        scanner.feed(html_text or "")
    except Exception:  # malformed markup: no note rather than a false one
        pass
    return sorted(scanner.found)


def sanitize_html(text):
    """Sanitize feed-supplied HTML: tag/attribute allow-lists plus
    the url_scheme_filter scheme allow-list, applied once so every
    output enforces exactly the same policy."""
    if not text:
        return ""
    return _CLEANER.clean(_SCRIPT_STYLE_RE.sub("", text))


def content_or_summary(entry):
    """Prefer Atom <content> (full text) over <summary> (teaser).

    feedparser mirrors content into summary only when the entry has no
    summary of its own; when both exist, summary holds just the short
    version, so the content blocks are checked first.  Both fields are
    feed-supplied HTML; sanitize_html() is the single enforcement point
    (feeds are parsed with sanitize_html=False).
    """
    for block in entry.get("content", []):
        if block.get("value"):
            return block["value"]
        if block.get("base64"):
            try:
                return base64.b64decode(block["base64"]).decode(
                    "utf-8", "replace")
            except (TypeError, ValueError):
                pass
    return entry.get("summary", "")


# URL schemes that address the local filesystem rather than the network.
LOCAL_URL_SCHEMES = ("", "file")


def _annotate(level, message):
    """Also raise a GitHub Actions annotation inside Actions runs."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        print(f"::{level} title=pyplanet2::{message}")


def _feed_problem(feed_url, feed):
    """None when the feed is usable; else ("fatal"|"skip", reason).

    A missing local file and a corrupt one look identical to
    feedparser (both are XML parse errors), so existence is checked
    explicitly to name them apart.  A configured local feed that
    cannot be read is a broken setup and fatal; an unreachable remote
    feed merely skips, since a transient network problem should not
    stop a build.  A valid but empty feed is fine and silent.
    """
    scheme = urlparse(feed_url).scheme.lower()
    if scheme in LOCAL_URL_SCHEMES:
        path = Path(urlparse(feed_url).path or feed_url)
        if not path.exists():
            return "fatal", f"local feed file not found: {path}"
    if not feed.entries and feed.bozo:
        reason = str(getattr(feed, "bozo_exception", "") or "unparsable feed")
        if scheme in LOCAL_URL_SCHEMES:
            return "fatal", f"local feed unreadable: {reason}"
        return "skip", reason
    return None


def fetch_all_items(config):
    """Fetch and parse all items from configured feeds.

    The item dicts are the internal contract between this function,
    localize_images() and the two generators below: "dt" (aware
    datetime), "feed_title", "site", "icon" (plain strings,
    "" when unset), "title", "link" (scheme-checked by safe_link),
    "summary" (sanitized HTML), "feed_id" (index of the feed in the
    config) and "removed_content" (the sorted, lowercased labels for
    content readers would miss: the names of elements the sanitizer
    dropped, the notes localize_images() adds for images it could not
    bring into the cache, and the attachments an entry carries outside
    its HTML; empty when nothing was lost).  localize_images() may
    add "img_map".

    Every URL that leaves here is absolute -- "link" and the URLs
    inside "summary" are resolved to absolute ones, so no later stage
    ever has to guess what a relative URL was meant to point at.  The
    lone exception is a feed configured as a local file path, which
    carries no address to resolve against.
    """
    # Optional pool-wide age filter (0/unset = keep all ages); applies
    # to every output.  Undated posts fall back to epoch and thus age
    # out when this is set.
    age_days = (config.get("limits") or {}).get("max_age_days", 0)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=age_days)
              if age_days else None)

    items = []

    for feed_id, feed_config in enumerate(config["feeds"]):
        feed_url = feed_config["feed"]
        # prefer_summary: use the short Atom <summary> even when the
        # entry also carries full <content> (default: full text wins).
        prefer_summary = feed_config.get("prefer_summary", False)
        # feedparser's own sanitizer and URI resolver both stay off: the
        # bleach cleaner in sanitize_html() is the single policy point,
        # lost_content_tags() must see the raw markup, and the resolver
        # resolves against the feed url (wrong for posts in
        # subdirectories) while also turning plain #anchors into links
        # to the feed document.  Feed-level fields such as the entry
        # link are resolved by feedparser either way.
        feed = feedparser.parse(feed_url, resolve_relative_uris=False,
                                sanitize_html=False)
        # Fallback base for entries that carry no usable link.  A local
        # file path is not an address, so such feeds keep their URLs as
        # written.
        feed_base = (feed_url if urlparse(feed_url).scheme in ("http", "https")
                     else "")
        
        problem = _feed_problem(feed_url, feed)
        if problem:
            kind, reason = problem
            if kind == "fatal":
                print(f"ERROR: {feed_url}: {reason}", file=sys.stderr)
                _annotate("error", f"{feed_url}: {reason}")
                sys.exit(1)
            print(f"WARNING: feed skipped (continuing without it): "
                  f"{feed_url} -- {reason}")
            _annotate("warning", f"{feed_url}: {reason}")
            continue

        # Display title: the locally configured name only -- a feed's
        # own <title> is remote input and never displayed (validate
        # requires name; the URL fallback only concerns calls that
        # bypass validation).
        feed_title = feed_config.get("name", feed_url)
        site = feed_config.get("site", feed_url)
        icon = feed_config.get("icon", "")

        for entry in feed.entries:
            title = entry.get("title", "(no title)")
            link = safe_link(entry.get("link", "#"))
            summary = (entry.get("summary", "") if prefer_summary
                       else content_or_summary(entry))
            removed = lost_content_tags(summary)
            # Attachments a feed carries outside the entry's HTML -- an
            # RSS <enclosure> or the Atom link with rel="enclosure" --
            # are invisible to the sanitizer, so they are handled here:
            # the page cannot show them, so they are dropped like any
            # other lost content (never fetched, never linked, and so
            # no URL of them reaches a visitor) and named in the same
            # note.  "audio"/"video" reuse the element vocabulary;
            # anything else reads as a plain "attachment".
            for enclosure in entry.get("enclosures") or []:
                kind = (enclosure.get("type") or "").split("/")[0].lower()
                removed.append(kind if kind in ("audio", "video")
                               else "attachment")
            removed = sorted(set(removed), key=str.lower)
            # Everything leaves this function with absolute URLs: a
            # relative one on a planet page would resolve against the
            # planet rather than the blog it came from, and the
            # aggregated Atom feed forbids them outright.  URLs inside a
            # post resolve against that post's own link, which is the
            # base blogs with posts in subdirectories need; an entry
            # without a usable link falls back to the feed url.
            summary = make_urls_absolute(summary, _item_base(link, feed_base))
            # Single sanitization point: feed-supplied HTML passes
            # bleach exactly once, so the HTML view and the aggregated
            # Atom feed always enforce one and the same policy.
            summary = sanitize_html(summary)
            dt = parse_dt(entry)
            if cutoff and dt < cutoff:
                continue

            items.append({
                "dt": dt,
                "feed_id": feed_id,
                "feed_title": feed_title,
                "site": site,
                "icon": icon,
                "title": title,
                "link": link,
                "summary": summary,
                "removed_content": removed,
            })

    # Sort by date, newest first
    items.sort(key=lambda x: x["dt"], reverse=True)
    return items


def generate_atom_feed(items, output_file, config):
    """Generate an Atom feed from the items."""
    # Limit to max_feed_items for the feed
    feed_items = items[:config["limits"]["max_feed_items"]]

    feed = Atom1Feed(
        title=config["site"]["title"],
        link=config["site"]["site_url"],
        description="",
        feed_url=config["site"]["atom_feed_url"],
        # Stable feed id (Atom <id>): defaults to the feed's own URL;
        # set site.feed_guid to keep a permanent id if the URL ever moves.
        feed_guid=config["site"].get("feed_guid", config["site"]["atom_feed_url"]),
    )

    for item in feed_items:
        # readers cannot resolve relative paths, so images get the
        # absolute ("atom") cached copies when the image cache is on
        summary = rewrite_images(item["summary"], item.get("img_map"), "atom")
        # The same "content not shown" note the HTML view renders,
        # prepended so it leads the entry: feeds are read on their
        # own, where no post-card context would carry the warning.
        if item.get("removed_content"):
            summary = ("<p>Some embedded content from this post is not "
                       "shown here (" + ", ".join(item["removed_content"]) +
                       ") - consider seeing the original post.</p>"
                       + (summary or ""))
        feed.add_item(
            title=item["title"],
            link=item["link"],
            description=summary or None,
            unique_id=item["link"],
            updateddate=item["dt"],
            author_name=item["feed_title"],
        )

    Path(output_file).write_text(feed.writeString("utf-8"), encoding="utf-8")
    print(f"Generated Atom feed: {output_file} ({len(feed_items)} items)")


def generate_html_view(items, output_file, template_dir, config):
    """Generate a static HTML view using Jinja2 template."""
    # Single pass over the (newest-first) pool: at most
    # max_posts_per_feed posts per feed (0/unset = unlimited; newest
    # win), stopping once html_view_limit posts are gathered.  Render
    # contexts are copies: the shared item dicts stay untouched, so
    # the formatted date and the html-mode image rewrite never leak
    # into the Atom generator or a repeated run.
    limit = config["limits"]["html_view_limit"]
    per_feed = config["limits"].get("max_posts_per_feed", 0)
    counts = {}
    html_items = []
    for item in items:
        if per_feed:
            n = counts.get(item["feed_id"], 0)
            if n >= per_feed:
                continue
            counts[item["feed_id"]] = n + 1
        rendered = dict(item)
        rendered["date"] = item["dt"].strftime("%Y-%m-%d %H:%M UTC")
        if item.get("img_map"):
            rendered["summary"] = rewrite_images(
                item["summary"], item["img_map"], "html")
        html_items.append(rendered)
        if len(html_items) >= limit:
            break

    # Jinja2 environment (autoescape on; only bleach-sanitized values
    # are marked |safe in the template).  A configured template_dir is
    # searched first: templates there can shadow the bundled ones by
    # name or {% extends %} them via the package-dir fallback.
    paths = config.get("paths") or {}
    user_dir = paths.get("template_dir")
    env = Environment(loader=FileSystemLoader(
        [user_dir, template_dir] if user_dir else template_dir),
        autoescape=True)
    template = env.get_template(paths.get("template", "planet.html"))

    # Feed list for theme templates (e.g. a sidebar): every configured
    # feed, named by its local name only.
    feeds = [{"title": fc.get("name", fc["feed"]), "feed": fc["feed"],
              "site": fc.get("site", fc["feed"]),
              "icon": fc.get("icon", "")} for fc in config["feeds"]]

    html_content = template.render(
        posts=html_items,
        feeds=feeds,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        site_title=config["site"]["title"],
        css_files=config["output"].get("css", []),
        logo=config["output"].get("logo", ""),
        favicon=config["output"].get("favicon", ""),
        atom_feed_url=config["site"]["atom_feed_url"]
    )

    Path(output_file).write_text(html_content, encoding="utf-8")
    print(f"Generated HTML view: {output_file} ({len(html_items)} items)")


def localize_site_assets(config, fetcher=None):
    """Cache the site-level images named by the config itself.

    The favicon and the logo are the operator's own URLs rather than a
    feed's, so they are localized whether or not image caching is on: a
    remote one is fetched by the build and served from the same origin,
    and one the build cannot take is dropped rather than left for the
    visitor to load.  Stylesheets (``output.css``) are deliberately not
    fetched at all -- those are loaded by the visitor from wherever the
    config points, and a config is trusted input.

    Returns the urls whose copy the page will link, the set prune_cache()
    must therefore keep whatever its age.
    """
    touched = set()
    for key in ("favicon", "logo"):
        url = config["output"].get(key)
        if url:
            config["output"][key] = localize_site_image(url, config, fetcher)
            if config["output"][key]:
                touched.add(url)
    return touched


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Blog aggregator: combines RSS feeds into an Atom feed and HTML view.")
    parser.add_argument("config", help="path to config file (required)")
    args = parser.parse_args(argv)

    config = validate_config(load_config(args.config))

    print("Fetching feeds...")
    items = fetch_all_items(config)
    print(f"Total items fetched: {len(items)}")

    touched = set()
    if config.get("images"):
        print("Localizing feed images...")
        touched |= set(localize_images(items, config))

    touched |= localize_site_assets(config)

    # Pruning last, and told what the two passes above kept a copy for:
    # the images the output is about to link are never deleted, whatever
    # their age, so a build cannot cut the ground out from under itself.
    dropped, removed = prune_cache(config, touched)
    if dropped or removed:
        print(f"Pruned {dropped} expired entries and {removed} unreferenced "
              "files from the image cache")

    print("Generating Atom feed...")
    generate_atom_feed(items, config["output"]["atom_feed"], config)

    print("Generating HTML view...")
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)

    print("Done!")


if __name__ == "__main__":
    main()