#!/usr/bin/env python3
"""
Blog aggregator that combines RSS feeds into:
1. An aggregated Atom feed (atom.xml)
2. A static HTML view of the last 10 posts (planet.html)

Configuration is loaded from a YAML file (config.yaml by default,
or pass a path as the first argument).
"""
import argparse
import html
import sys
from datetime import datetime, timezone
from pathlib import Path

import bleach
import feedparser
import yaml
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


def fetch_all_items(config):
    """Fetch and parse all items from configured feeds."""
    items = []

    for feed_config in config["feeds"]:
        feed_url = feed_config["url"]
        feed = feedparser.parse(feed_url)
        
        # Use configured name, or fall back to feed title or URL
        feed_title = feed_config.get("name", feed.feed.get("title", feed_url))
        author = feed_config.get("author", feed_title)
        site = feed_config.get("site", feed_url)

        for entry in feed.entries:
            title = entry.get("title", "(no title)")
            link = entry.get("link", "#")
            summary = entry.get("summary", "")
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
    
    now = datetime.now(timezone.utc)
    
    # Build Atom XML
    parts = [
        '<?xml version="1.0" encoding="utf-8"?>',
        '<feed xmlns="http://www.w3.org/2005/Atom">',
        f'  <title>{escape_xml(config["site"]["title"])}</title>',
        f'  <updated>{now.strftime("%Y-%m-%dT%H:%M:%SZ")}</updated>',
        '  <id>urn:uuid:planet-feed</id>',
        f'  <link href="{escape_xml(config["site"]["site_url"])}" rel="alternate"/>',
        f'  <link href="{escape_xml(config["site"]["atom_feed_url"])}" rel="self"/>',
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
        logo=config["output"].get("logo", "")
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


def escape_xml(text):
    """Escape special characters for XML."""
    return html.escape(text, quote=True)


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