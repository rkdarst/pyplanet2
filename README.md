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
# or with a specific config file:
python3 pyplanet2.py path/to/config.yaml
```

## Configuration

Settings live in `config.yaml` (or the config file passed as the
first argument to the script). Edit `config.yaml` to customize:

- `site` - Site title and URLs (`title`, `site_url`, `atom_feed_url`)
- `output` - Output filenames (`atom_feed`, `html_view`)
- `limits` - `max_feed_items` (default: 100) and `html_view_limit` (default: 10)
- `feeds` - List of feeds to aggregate; each entry has a `url`
  (local paths work for offline testing) and optional `name`,
  `author`, and `site` metadata