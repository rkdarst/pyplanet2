#!/usr/bin/env python3
"""
Blog aggregator that combines RSS feeds into:
1. An aggregated Atom feed (atom.xml)
2. A static HTML view of the last 10 posts (planet.html)
"""
import html
from datetime import datetime, timezone
from pathlib import Path

import feedparser
from jinja2 import Environment, FileSystemLoader

# Configuration
FEEDS = [
    "https://rkd.zgib.net/blog/atom.xml",
    "https://digitalflapjack.com/index.xml",
]

# Output settings
ATOM_FEED_FILE = "atom.xml"
HTML_VIEW_FILE = "planet.html"
MAX_FEED_ITEMS = 100  # Maximum items in the aggregated Atom feed
HTML_VIEW_LIMIT = 10  # Number of posts to show in HTML view

# Template directory
TEMPLATE_DIR = Path(__file__).parent / "templates"


def parse_dt(entry):
    """Parse publication or update date from feed entry."""
    if getattr(entry, "published_parsed", None):
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    if getattr(entry, "updated_parsed", None):
        return datetime(*entry.updated_parsed[:6], tzinfo=timezone.utc)
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def fetch_all_items():
    """Fetch and parse all items from configured feeds."""
    items = []

    for feed_url in FEEDS:
        feed = feedparser.parse(feed_url)
        feed_title = feed.feed.get("title", feed_url)

        for entry in feed.entries:
            title = entry.get("title", "(no title)")
            link = entry.get("link", "#")
            summary = entry.get("summary", "")
            dt = parse_dt(entry)

            items.append({
                "dt": dt,
                "feed_title": feed_title,
                "title": title,
                "link": link,
                "summary": summary,
            })

    # Sort by date, newest first
    items.sort(key=lambda x: x["dt"], reverse=True)
    return items


def generate_atom_feed(items, output_file):
    """Generate an Atom feed from the items."""
    # Limit to MAX_FEED_ITEMS for the feed
    feed_items = items[:MAX_FEED_ITEMS]
    
    now = datetime.now(timezone.utc)
    
    # Build Atom XML
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        '  <title>Planet</title>',
        f'  <updated>{now.strftime("%Y-%m-%dT%H:%M:%SZ")}</updated>',
        '  <id>urn:uuid:planet-feed</id>',
        '  <link href="https://example.com/planet/" rel="alternate"/>',
        '  <link href="https://example.com/planet/atom.xml" rel="self"/>',
    ]

    for item in feed_items:
        parts.append("  <entry>")
        parts.append(f'    <title>{escape_xml(item["title"])}</title>')
        parts.append(f'    <id>{escape_xml(item["link"])}</id>')
        parts.append(f'    <link href="{escape_xml(item["link"])}"/>')
        parts.append(f'    <updated>{item["dt"].strftime("%Y-%m-%dT%H:%M:%SZ")}</updated>')
        parts.append(f'    <author><name>{escape_xml(item["feed_title"])}</name></author>')
        if item["summary"]:
            parts.append(f'    <summary>{escape_xml(item["summary"])}</summary>')
        parts.append("  </entry>")

    parts.append("</feed>")
    
    Path(output_file).write_text("\n".join(parts), encoding="utf-8")
    print(f"Generated Atom feed: {output_file} ({len(feed_items)} items)")


def generate_html_view(items, output_file, template_dir):
    """Generate a static HTML view using Jinja2 template."""
    # Limit to HTML_VIEW_LIMIT for the HTML preview
    html_items = items[:HTML_VIEW_LIMIT]
    
    # Prepare items for template with formatted date
    for item in html_items:
        item["date"] = item["dt"].strftime("%Y-%m-%d %H:%M UTC")
    
    # Setup Jinja2 environment
    env = Environment(loader=FileSystemLoader(template_dir))
    template = env.get_template("planet.html")
    
    # Render template
    html = template.render(
        posts=html_items,
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    
    Path(output_file).write_text(html, encoding="utf-8")
    print(f"Generated HTML view: {output_file} ({len(html_items)} items)")


def escape_xml(text):
    """Escape special characters for XML."""
    return html.escape(text, quote=True)


def main():
    """Main entry point."""
    print("Fetching feeds...")
    items = fetch_all_items()
    print(f"Total items fetched: {len(items)}")
    
    print("Generating Atom feed...")
    generate_atom_feed(items, ATOM_FEED_FILE)
    
    print("Generating HTML view...")
    generate_html_view(items, HTML_VIEW_FILE, TEMPLATE_DIR)
    
    print("Done!")


if __name__ == "__main__":
    main()