# Planet blog aggregator

This is a blog aggregator that takes a list of RSS/Atom feeds
(configured in yaml) and makes a combined Atom feed and HTML view.
When I looked in 2026, I couldn't find any easy to install planet
software in Python, so I created this.

Features:

* Installation as a pip package, run via `pyplanet2 config.yaml`
* Configuration via a yaml file.
* Outputs a .html for viewing and atom.xml for feed readers.
* Easy usage by Github Pages and similar.
* Extensive HTML sanitization (should err on the side of caution, but
  it is AI-generated so please report problems you notice)
* Caching images for privacy and to reduce web traffic of feeds
  (this is a bit fragile, validate it works for each feed).
* Templating with jinja2 and custom CSS may be inserted which should
  allow you to override any config.  Note the config and format may
  not be very stable right now.

Status: This is still (2026) in active development and you probably
shouldn't expect it to be stable yet.

Warning: the code is generated ("AI").  I partly did it as a test,
partly because I needed it.  Contributions should be in the form of a
request for me or prompts for *my* content generator to produce by my
standards.  Large auto-generated pull requests won't be reviewed
(unless you reach the status of contributor).  Given it is
machine-generated, it is CC-0 and you are welcome to fork and develop
further.

**Everything about this line is written by a human.  Everything below
is generated content ("AI") and you should adjust your reading to
match.**


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

A local `feeds[].url` path that does not exist (or cannot be parsed)
stops the build with an error; an unreachable remote feed is skipped
with a `WARNING` instead.  In GitHub Actions runs both are also
flagged as workflow annotations.

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
  # max_posts_per_feed: 5           # optional; HTML page only: cap posts per
                                    # feed, newest win (0/unset = unlimited)
  # max_age_days: 90                # optional: drop posts older than this
                                    # from all outputs (0/unset = unlimited)

# Feeds to aggregate
feeds:
  - feed: "https://blog.example.org/feed.xml"  # required; a local path also
                                    # works, for offline testing
    name: "Some Blog"             # required; the ONLY displayed feed title
                                    # (a feed's own remote title is untrusted
                                    # input and never used); also the name
                                    # templates see in the feeds list
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

## Customizing the HTML view

The HTML page is a Jinja2 template.  Both `paths` keys are optional;
without them the bundled `planet.html` renders as-is.  A user template
normally extends that base and redefines only the blocks it needs:

```yaml
paths:
  template_dir: ./themes      # optional; searched before the built-ins
  template: dark.html         # optional; default planet.html
```

```jinja
{# themes/dark.html #}
{% extends "planet.html" %}
{% block styles %}{{ super() }}
<style>:root { --bg: #111; --fg: #ddd; --title: #6af; }</style>
{% endblock %}
{% block footer %}<footer>My planet &mdash; powered by pyplanet2</footer>{% endblock %}
```

Overridable blocks: `title`, `styles`, `head_extra`, `header`,
`generated_info`, `posts`, `post`, `post_icon`, `post_meta`,
`post_summary`, `sidebar` (right-side feed list), `footer`, `scripts`.
The four `post*` blocks are `scoped`, so `item` is available in them.
A template that does not `extends` replaces the page completely.
Variables: `site_title`, `atom_feed_url`, `generated_at`, `logo`,
`css_files`, `posts` (each with `title`, `link`, `date`, `feed_title`,
`site`, `icon`, `summary`) and `feeds` (every configured feed as
`title`/`feed`/`site`/`icon`); the base template uses it for the
default right-hand feed sidebar, which a theme can restyle or replace:

```jinja
{% block sidebar %}
<aside>{% for f in feeds %}
  <a href="{{ f.site }}">{{ f.title }}</a>
{% endfor %}</aside>
{% endblock %}
```

### Color palette

Every visual default hangs off these CSS custom properties declared
on `:root` in the base template; override them from an `output.css`
stylesheet or a `styles` block -- no template needed:

| Variable | Default | Used for |
|---|---|---|
| `--bg` / `--fg` | `#fff` / `#222` | page background / body text |
| `--brand` | `#06c` | site title next to the logo (same default as `--title`, set separately) |
| `--title` | `#06c` | post titles, sidebar links, expand buttons |
| `--link` | `var(--title)` | default color for every link (post titles, sidebar and feed-name links override) |
| `--line` | `#ddd` | card and sidebar borders, placeholders |
| `--muted` / `--faint` | derived from `--fg`/`--bg` | meta lines, footer |
| `--shadow` | derived from `--fg` | expand-button shadow |
| `--post-clamp` | `45vh` | collapsed post height |

The derived tiers (`--muted`, `--faint`, `--shadow`, `--link`) follow
`--fg`/`--bg`/`--title` automatically, so a complete dark theme is:

```css
:root { --bg: #111; --fg: #ddd; --title: #6af; }
```

The template also ships an **automatic dark theme**: when the
visitor's browser prefers dark mode, the five core values swap via a
`prefers-color-scheme` media block (`--bg: #111`, `--fg: #ddd`,
`--title`/`--brand: #6af`, `--line: #333`) and the derived tiers
follow.  Stylesheets listed under `output.css` load after it, so your
own plain `:root` values apply in both modes; to customize dark mode
only, define your own `prefers-color-scheme` media block.

Note: do not name your own template `planet.html` inside
`template_dir` if it also `{% extends "planet.html" %}` -- that
resolves to itself; pick a distinct name.

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
