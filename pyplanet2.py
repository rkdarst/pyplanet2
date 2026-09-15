#!/usr/bin/env python3
"""
Blog aggregator that combines RSS feeds into:
1. An aggregated Atom feed (atom.xml)
2. A static HTML view of the last 10 posts (planet.html)

Configuration is loaded from a YAML file (config.yaml by default,
or pass a path as the first argument).
"""
import argparse
import sys
from datetime import datetime, timezone
from html import escape as html_escape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin, urlparse

import bleach
import feedparser
import yaml
from feedgenerator import Atom1Feed
from jinja2 import Environment, FileSystemLoader

# Default configuration file
DEFAULT_CONFIG_FILE = Path(__file__).parent / "config.yaml"


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


# Tag/attribute pairs whose values are single URLs to resolve against
# the entry's own link (feedparser resolves against the *feed* URL by
# default, which is wrong for per-post relative paths).
RESOLVED_URL_ATTRS = {
    ("a", "href"),
    ("img", "src"),
}


def _resolve_url(url, base_url):
    """Resolve a single URL against base_url, leaving absolute ones alone."""
    url = url.strip()
    if not url or url.startswith("#") or urlparse(url).scheme:
        return url
    return urljoin(base_url, url)


def _resolve_srcset(srcset, base_url):
    """Resolve every candidate URL in a srcset attribute, keeping descriptors."""
    resolved = []
    for candidate in srcset.split(","):
        tokens = candidate.split()
        if not tokens:
            continue
        url = _resolve_url(tokens[0], base_url)
        resolved.append(" ".join([url] + tokens[1:]))
    return ", ".join(resolved)


class _AbsoluteURLParser(HTMLParser):
    """Re-emit HTML with relative URLs resolved against a base URL."""

    def __init__(self, base_url):
        # convert_charrefs=False so entities round-trip untouched
        super().__init__(convert_charrefs=False)
        self.base_url = base_url
        self.parts = []

    def result(self):
        return "".join(self.parts)

    def _serialize_attrs(self, tag, attrs):
        out = []
        for name, value in attrs:
            lower = name.lower()
            if value is not None:
                if (tag, lower) in RESOLVED_URL_ATTRS:
                    value = _resolve_url(value, self.base_url)
                elif lower == "srcset" and tag in ("img", "source"):
                    value = _resolve_srcset(value, self.base_url)
                out.append(f' {name}="{html_escape(value, quote=True)}"')
            else:
                out.append(f" {name}")
        return "".join(out)

    def handle_starttag(self, tag, attrs):
        self.parts.append(f"<{tag}{self._serialize_attrs(tag, attrs)}>")

    def handle_startendtag(self, tag, attrs):
        self.parts.append(f"<{tag}{self._serialize_attrs(tag, attrs)} />")

    def handle_endtag(self, tag):
        self.parts.append(f"</{tag}>")

    def handle_data(self, data):
        self.parts.append(html_escape(data, quote=False))

    def handle_entityref(self, name):
        self.parts.append(f"&{name};")

    def handle_charref(self, name):
        self.parts.append(f"&#{name};")

    def handle_comment(self, data):
        self.parts.append(f"<!--{data}-->")

    def handle_decl(self, decl):
        self.parts.append(f"<!{decl}>")

    def unknown_decl(self, data):
        self.parts.append(f"<![{data}]>")

    def handle_pi(self, data):
        self.parts.append(f"<?{data}>")


def make_urls_absolute(html_text, base_url):
    """Rewrite relative src/href/srcset URLs in HTML to absolute ones.

    URLs are resolved against base_url (the feed item's own link), so
    content works identically once embedded in the aggregated page.
    Absolute URLs, data: URIs, and plain #anchors are left untouched.
    """
    if not html_text or not base_url or base_url == "#":
        return html_text
    parser = _AbsoluteURLParser(base_url)
    parser.feed(html_text)
    parser.close()
    return parser.result()


def fetch_all_items(config):
    """Fetch and parse all items from configured feeds."""
    items = []

    for feed_config in config["feeds"]:
        feed_url = feed_config["url"]
        # Turn off feedparser's own HTML sanitizer and relative-URI
        # resolver: we sanitize with bleach and resolve URLs against each
        # entry's link instead (feedparser resolves against the feed URL,
        # and its sanitizer strips srcset and other modern attributes).
        feed = feedparser.parse(feed_url, sanitize_html=False,
                                resolve_relative_uris=False)
        
        # Use configured name, or fall back to feed title or URL
        feed_title = feed_config.get("name", feed.feed.get("title", feed_url))
        author = feed_config.get("author", feed_title)
        site = feed_config.get("site", feed_url)

        for entry in feed.entries:
            title = entry.get("title", "(no title)")
            link = entry.get("link", "#")
            summary = entry.get("summary", "")
            # Sanitize with bleach, then rewrite relative URLs (images,
            # links) against the entry's own link so they still resolve
            # when shown on the aggregated page
            summary = make_urls_absolute(sanitize_html(summary), link)
            dt = parse_dt(entry)

            items.append({
                "dt": dt,
                "feed_title": feed_title,
                "author": author,
                "site": site,
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
        feed.add_item(
            title=item["title"],
            link=item["link"],
            description=item["summary"] or None,
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
    
    # Prepare items for template with formatted date and sanitized summary
    for item in html_items:
        item["date"] = item["dt"].strftime("%Y-%m-%d %H:%M UTC")
        # Sanitize the summary HTML using bleach
        if item.get("summary"):
            item["summary"] = sanitize_html(item["summary"])
    
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
        'img': ['src', 'srcset', 'alt', 'title', 'width', 'height'],
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
    parser.add_argument("config", nargs="?", default=str(DEFAULT_CONFIG_FILE),
                        help="path to config file (default: config.yaml next to the script)")
    args = parser.parse_args(argv)

    config = load_config(args.config)

    print("Fetching feeds...")
    items = fetch_all_items(config)
    print(f"Total items fetched: {len(items)}")

    print("Generating Atom feed...")
    generate_atom_feed(items, config["output"]["atom_feed"], config)

    print("Generating HTML view...")
    generate_html_view(items, config["output"]["html_view"], TEMPLATE_DIR, config)

    print("Done!")


if __name__ == "__main__":
    main()