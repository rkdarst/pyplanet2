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

- Python 3.10+
- feedparser, feedgenerator, jinja2, bleach, pyyaml
  (installed automatically with the package)

## Usage

Install the package, then always pass a config file:

```bash
pip install .
pyplanet2 config.yaml
# (also runnable without installing:  python -m pyplanet2 config.yaml)
```

Relative output paths in the config resolve against the current
directory, so run it from where the outputs should land.

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
  Atom feeds often carry both a short `summary` and the full text as
  `content`; the full text is used by default, and
  `prefer_summary: true` selects the short teaser instead.

## Image caching

Defining an `images` section makes the build download every image the
feeds reference (post images and feed icons) into a local directory
that is published together with the site, and rewrite the references
to those copies.  Visitors then only ever load images from your own
domain (no IP disclosure to feed hosts), posts keep their images even
if the upstream ones vanish, and the cache persists between CI runs
via the deployed `gh-pages` branch: entries younger than `ttl_days`
are not touched at all, older ones are revalidated with a conditional
request that transfers nothing when the image is unchanged.

```yaml
images:
  dir: "images"   # cache = deploy output directory
  ttl_days: 1     # skip revalidation for entries younger than this
  # base_url: "https://example.com/planet/"  # default: site.site_url
```

Images are fetched with http(s)-only, public-host, timeout and size
guards; responses must be of an `image/*` content type, and files are
stored under hash-derived names so no URL can escape the cache
directory.  SVG images are deliberately not cached (they could carry
scripts when served same-origin), and any failure simply keeps the
original remote URL, so image problems never break a build.

## Security notes

Feed content is treated as untrusted input.  Feed-supplied HTML in
post summaries is sanitized once at fetch time -- scripts, event
handler attributes, `javascript:` URLs and embeds such as `<iframe>`
are stripped, and both the HTML view and the aggregated Atom feed
enforce exactly the same policy.  Post links with any scheme other
than http(s) are rendered inert (`#`).  As a side effect, `data:` URIs
in feed images do not load.  The config file is trusted input: feed
`url` entries may reference local files, intended for offline testing.

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