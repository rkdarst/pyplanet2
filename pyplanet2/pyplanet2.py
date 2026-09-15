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
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import bleach
import feedparser
import yaml
from feedgenerator import Atom1Feed
from jinja2 import Environment, FileSystemLoader

from .imagecache import localize_images, rewrite_images

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

    URLs are resolved against base_url (the feed item's own link), so
    embedded images and links still work once shown on the aggregated
    page.  Absolute URLs and plain #anchors are left untouched.
    Enabled per feed via the resolve_urls config option.
    """
    if not html_text or not base_url or base_url == "#":
        return html_text

    def replace(match):
        quoted = match.group(2)
        value = quoted if quoted is not None else match.group(3)
        quote = '"' if quoted is not None else "'"
        return f"{match.group(1)}={quote}{_resolve_url(value, base_url)}{quote}"

    return REL_URL_ATTR_RE.sub(replace, html_text)


def safe_link(url):
    """Return url, or "#" when its scheme is unsafe.

    Only post summaries pass through the bleach sanitizer, so links
    taken straight from feeds are checked here instead: a malicious
    feed could otherwise plant a clickable javascript: link, which the
    templates' HTML escaping would happily preserve.  NUL bytes are
    dropped first because browsers remove them before resolving URLs
    (XML itself cannot carry them, so this is defense-in-depth).
    """
    url = url.replace("\x00", "").strip()
    if not url:
        return "#"
    scheme = urlparse(url).scheme.lower()
    return url if scheme in ("", "http", "https") else "#"


def content_or_summary(entry):
    """Prefer Atom <content> (full text) over <summary> (teaser).

    feedparser mirrors content into summary only when the entry has no
    summary of its own; when both exist, summary holds just the short
    version, so the content blocks are checked first.  Both fields are
    sanitized by feedparser's built-in HTML sanitizer.
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


def fetch_all_items(config):
    """Fetch and parse all items from configured feeds."""
    items = []

    for feed_config in config["feeds"]:
        feed_url = feed_config["url"]
        # resolve_urls: rewrite relative URLs inside items against each
        # item's own link, instead of feedparser's default of resolving
        # against the feed URL (wrong for blogs with posts in
        # subdirectories).  Disabled by default.
        resolve_urls = feed_config.get("resolve_urls", False)
        # prefer_summary: use the short Atom <summary> even when the
        # entry also carries full <content> (default: full text wins).
        prefer_summary = feed_config.get("prefer_summary", False)
        feed = feedparser.parse(feed_url, resolve_relative_uris=not resolve_urls)
        
        # Use configured name, or fall back to feed title or URL
        feed_title = feed_config.get("name", feed.feed.get("title", feed_url))
        author = feed_config.get("author", "")
        site = feed_config.get("site", feed_url)
        icon = feed_config.get("icon", "")

        for entry in feed.entries:
            title = entry.get("title", "(no title)")
            link = safe_link(entry.get("link", "#"))
            summary = (entry.get("summary", "") if prefer_summary
                       else content_or_summary(entry))
            if resolve_urls:
                summary = make_urls_absolute(summary, link)
            # Single sanitization point: feed-supplied HTML passes
            # bleach exactly once, so the HTML view and the aggregated
            # Atom feed always enforce one and the same policy.
            summary = sanitize_html(summary)
            dt = parse_dt(entry)

            items.append({
                "dt": dt,
                "feed_title": feed_title,
                "author": author,
                "site": site,
                "icon": icon,
                "title": title,
                "link": link,
                "summary": summary,
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
    # Limit to html_view_limit for the HTML preview
    html_items = items[:config["limits"]["html_view_limit"]]
    
    # Prepare items for template with formatted dates; the summaries
    # were already sanitized once at fetch time.
    for item in html_items:
        item["date"] = item["dt"].strftime("%Y-%m-%d %H:%M UTC")
        if item.get("img_map"):
            item["summary"] = rewrite_images(item["summary"],
                                             item["img_map"], "html")
    
    # Setup Jinja2 environment (autoescape on; only bleach-sanitized
    # values are marked |safe in the template)
    env = Environment(loader=FileSystemLoader(template_dir), autoescape=True)
    template = env.get_template("planet.html")
    
    # Render template
    html_content = template.render(
        posts=html_items,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        site_title=config["site"]["title"],
        css_files=config["output"].get("css", []),
        logo=config["output"].get("logo", ""),
        atom_feed_url=config["site"]["atom_feed_url"]
    )
    
    Path(output_file).write_text(html_content, encoding="utf-8")
    print(f"Generated HTML view: {output_file} ({len(html_items)} items)")


def sanitize_html(text):
    """
    Sanitize HTML content using bleach.
    Allows only safe HTML tags while removing potentially dangerous ones.
    """
    if not text:
        return ""
    
    # Define allowed tags and attributes
    allowed_tags = [
        'p', 'br', 'strong', 'b', 'em', 'i', 'u', 'small',
        'a', 'ul', 'ol', 'li',
        'h1', 'h2', 'h3', 'h4', 'h5', 'h6',
        'blockquote', 'pre', 'code', 'img',
        'div', 'span', 'hr', 'table', 'thead', 'tbody', 'tr', 'th', 'td'
    ]
    
    allowed_attributes = {
        'a': ['href', 'title', 'rel'],
        'img': ['src', 'alt', 'title', 'width', 'height'],
    }
    
    return bleach.clean(
        text,
        tags=allowed_tags,
        attributes=allowed_attributes,
        strip=True
    )


def main(argv=None):
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Blog aggregator: combines RSS feeds into an Atom feed and HTML view.")
    parser.add_argument("config", help="path to config file (required)")
    args = parser.parse_args(argv)

    config = load_config(args.config)

    print("Fetching feeds...")
    items = fetch_all_items(config)
    print(f"Total items fetched: {len(items)}")

    if config.get("images"):
        print("Localizing feed images...")
        localize_images(items, config)

    print("Generating Atom feed...")
    generate_atom_feed(items, config["output"]["atom_feed"], config)

    print("Generating HTML view...")
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)

    print("Done!")


if __name__ == "__main__":
    main()