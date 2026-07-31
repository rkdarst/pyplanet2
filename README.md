# Planet blog aggregator

This is a blog aggregator that takes a list of RSS/Atom feeds and
makes a combined Atom feed. It also outputs a .html file of the last
10 feeds, which can be used as a static-site preview.

## Output files

- `atom.xml` - The aggregated Atom feed with up to 100 items
- `planet.html` - A static HTML view of the last 10 posts

## Requirements

- Python 3
- feedparser
- jinja2

## Usage

```bash
python3 pyplanet2.py
```

## Configuration

Edit `pyplanet2.py` to customize:

- `FEEDS` - List of RSS/Atom feed URLs to aggregate
- `MAX_FEED_ITEMS` - Maximum number of items in the Atom feed (default: 100)
- `HTML_VIEW_LIMIT` - Number of posts to show in HTML view (default: 10)
- `ATOM_FEED_FILE` - Output filename for the Atom feed
- `HTML_VIEW_FILE` - Output filename for the HTML view