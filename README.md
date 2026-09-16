# Planet blog aggregator

This is a blog aggregator that takes a list of RSS/Atom feeds
(configured in yaml) and makes a combined Atom feed and HTML view.  When
I looked in 2026, I couldn't find any easy to install planets, so I went
with this.

Warning: this is generated content ("AI").  I partly did it as a test,
but consider this before you try to modify this as a human.  So far,
everything below this comment is automatically generated.  Consider
asking me (a human) to fix it up before trying to extensively use this.
Or ask me to ask the content generator to add things.


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
first argument to the script).  A commented sample is below; the
optional entries are commented out.  See [`config-test.yaml`](config-test.yaml)
for a runnable config.

```yaml
# General site settings
site:
  title: "My Planet"                # Site title
  site_url: "https://example.com/planet/"           # Home page of the site
  atom_feed_url: "https://example.com/planet/atom.xml"  # Where the feed lives
  # feed_guid: "urn:uuid:60a76c80-d399-11d9-b93c-000000000000"
                                    # optional: a permanent id for the feed,
                                    # defaults to atom_feed_url (useful if the
                                    # URL might move)

# Output file paths
output:
  atom_feed: "atom.xml"             # Atom feed output file
  html_view: "planet.html"          # HTML view output file
  # css: ["custom.css"]             # optional: extra stylesheets (paths or
                                    # URLs) added after the built-in styling
  # logo: "logo.png"                # optional: header image; its height is
                                    # capped, never upscaled, width is free

# Item limits
limits:
  max_feed_items: 100               # Maximum items in the aggregated Atom feed
  html_view_limit: 10               # Number of posts shown on the HTML page

# Feeds to aggregate
feeds:
  - url: "https://blog.example.org/feed.xml"  # required; a local path also
                                    # works, for offline testing
    # name: "Some Blog"             # optional display name; defaults to the
                                    # feed's own title
    # author: "Jane Doe"            # optional; shown in the post meta line,
                                    # omitted from it when unset
    # site: "https://blog.example.org"  # optional link for the name/icon;
                                    # defaults to the feed url
    # icon: "https://blog.example.org/favicon.ico"
                                    # optional avatar beside each post; a grey
                                    # placeholder box is shown if unset
    # resolve_urls: true            # optional; resolve relative urls inside
                                    # this feed's items against each item's own
                                    # link instead of the feed url (default:
                                    # false) — for blogs that serve posts from
                                    # subdirectories
    # prefer_summary: true          # optional; use the short summary instead
                                    # of the full text when Atom feeds carry
                                    # both (default: false)

# An optional `images` section localizes referenced images; see the
# "Image caching" section below for its keys.
```

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

The SSRF guard blocks non-http(s) schemes and literal private or
loopback addresses and re-checks every redirect hop, but hostnames
are not resolved before connecting: a DNS name pointing at a local
address would therefore still be fetched at build time.  Only the
build machine is exposed that way -- visitors never are, since they
only ever load the cached copies.

## Security notes

Feed content is treated as untrusted input.  Feed-supplied HTML in
post summaries is sanitized once at fetch time -- scripts, event
handler attributes and embeds such as `<iframe>` are stripped, and
both the HTML view and the aggregated Atom feed enforce exactly the
same policy.  Every `href`/`src` in summaries and every post link is
additionally checked against a scheme allow-list (http, https,
relative URLs, mailto) using browser-equivalent URL cleaning, so
malformed shapes like `java`+tab+`script:` cannot slip through;
links with any other scheme are rendered inert (`#` or dropped).  As a side effect, `data:` URIs
in feed images do not load.  The config file is trusted input: feed
`url` entries may reference local files, intended for offline testing.

## Deployment

A GitHub Actions workflow (`.github/workflows/build.yml`) rebuilds
the planet on every push to `master` and on manual dispatch,
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