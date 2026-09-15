# Planet blog aggregator

This is a blog aggregator that takes a list of RSS/Atom feeds and
makes a combined Atom feed. It also outputs a .html file of the last
10 feeds, which can be used as a static-site preview.

## Output files

- `atom.xml` - The aggregated Atom feed with up to 100 items
- `planet.html` - A static HTML view of the last 10 posts; each post
  is shown in a card, and posts longer than about one screen are
  collapsed with an Expand/Collapse button that also indicates how
  long the post is ("250% of screen"; recomputed on window resize).
  The button sticks to the lower-left corner, so a long expanded post
  can be re-collapsed from any scroll position.
  Fully functional without JavaScript, which just disables the
  collapsing.  The collapsed height can be overridden by defining
  the `--post-clamp` CSS variable in a stylesheet listed under
  `output.css`.

## Requirements

- Python 3
- feedparser
- feedgenerator
- jinja2
- bleach
- pyyaml

## Usage

```bash
python3 pyplanet2.py
# or with a specific config file:
python3 pyplanet2.py path/to/config.yaml
```

## Configuration

Settings live in `config.yaml` (or the config file passed as the
first argument to the script). Edit `config.yaml` to customize:

- `site` - Site title and URLs (`title`, `site_url`, `atom_feed_url`,
  and an optional `feed_guid` — a permanent feed id that overrides
  the default of using `atom_feed_url`, useful if the feed URL moves)
- `output` - Output filenames (`atom_feed`, `html_view`), an optional
  `css` list of stylesheet paths/URLs inserted after the built-in
  styling of the HTML view, and an optional `logo` image path/URL
- `limits` - `max_feed_items` (default: 100) and `html_view_limit` (default: 10)
- `feeds` - List of feeds to aggregate; each entry has a `url`
  (local paths work for offline testing) and optional `name`,
  `author`, `site`, and `icon` metadata.  The `icon` (a face/logo
  image URL) renders beside each post, linked to `site` when set;
  feeds without an icon get a grey placeholder box. An entry may also set
  `resolve_urls: true` to rewrite relative image/link URLs inside
  that feed's items against each item's own link. By default
  relative URLs are resolved against the *feed* URL, which breaks
  images on blogs that serve posts from subdirectories
  (e.g. `…/blog/2026/post/` referencing `../images/pic.png`).

## Deployment

A GitHub Actions workflow (`.github/workflows/build.yml`) rebuilds
the planet on every push to `master` and once a day on a schedule,
then deploys `planet.html` (as `index.html`) and `atom.xml` to
GitHub Pages via `peaceiris/actions-gh-pages`.

Setup:

1. Enable Pages once: repo Settings -> Pages -> Source: *GitHub Actions*.
2. Point `site.site_url` and `site.atom_feed_url` in `config.yaml`
   at your Pages URLs, e.g. `https://<user>.github.io/<repo>/` and
   `https://<user>.github.io/<repo>/atom.xml`, so the links embedded
   in the HTML view and feed resolve correctly.

Note: scheduled workflows are delayed at peak times and are
automatically disabled after 60 days without repository activity
(they re-enable on the next push).