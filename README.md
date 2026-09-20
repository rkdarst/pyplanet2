# Planet blog aggregator

This is a blog aggregator that takes a list of RSS/Atom feeds
(configured in yaml) and makes a combined Atom feed and HTML view.
When I looked in 2026, I couldn't find any easy to install planet
software in Python, so I created this.

RSS/Atom feeds provide a way to syndicate blogs, news, and so on
without big tech platforms mediating our interactions.  They used to
be common, and now not so much - but they should probably come back.
People can make blogs with feeds either on various platforms or as a
static website, and there are various feed readers, either services
your can use or self-hosted.

Features:

* Installation as a pip package, run via `pyplanet2 config.yaml`
* Configuration via a yaml file.
* Outputs a .html for viewing and atom.xml for feed readers.
* Easy usage by Github Pages and similar.
* Privacy and security
  * Extensive HTML sanitization to remove interactive and remote
    elements.
  * Caching images for privacy and to reduce web traffic of upstream
    feeds
  * Still, both of the above are a bit fragile and machine-generated.
    They can be considered "nice for semi-trusted users" but not good
    enough for dedicated attackers.
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

**Everything above this line is written by a human.  Everything below
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
                                    # (loaded by the visitor, never fetched
                                    # by the build)
  # logo: "logo.png"                # optional: header image; its height is
                                    # capped, never upscaled, width is free;
                                    # a local file is used as given, or a URL
                                    # is fetched and cached
  # favicon: "favicon.ico"          # optional: browser tab icon; a local
                                    # file used as given, or a URL to cache

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
    # prefer_summary: true          # optional; use the short summary instead
                                    # of the full text when Atom feeds carry
                                    # both (default: false)

# An optional `images` section localizes referenced images; see the
# "Image caching" section below for its keys.
```

### Relative URLs are always made absolute

Feeds routinely carry relative URLs, and on an aggregated page those
would resolve against *your* site rather than the blog they came from;
the aggregated Atom feed requires absolute links in any case.  Every URL
is therefore resolved while the feed is read: each item's own link
against the feed document that carried it, and the URLs inside a post
against that post's link, which is the base blogs that serve posts from
subdirectories need.  Absolute URLs and plain `#anchors` are left
exactly as written, so an in-post anchor still stays on the page.  A
feed configured as a local file path is the one exception -- it offers
no address to resolve against, and exists for offline testing.  (Until
it became unconditional this was the per-feed `resolve_urls` option;
that key no longer exists, and an old config carrying it is simply
ignored.)

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
Variables: `site_title`, `atom_feed_url`, `generated_at`, `logo`, `favicon`,
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
  dir: "images-cached"  # cache = deploy output directory
  ttl_days: 1     # skip revalidation for entries younger than this
  # image_cache_max_bytes: 10485760  # larger images are dropped (10 MB)
  # base_url: "https://example.com/planet/"  # default: site.site_url
```

Images are fetched with http(s)-only, public-host, timeout and size
guards; responses must be of an `image/*` content type, and files are
stored under hash-derived names so no URL can escape the cache
directory.

**The cache is fail-closed.** An image it cannot bring in is removed
from the post rather than left pointing at the host the feed chose,
because a URL left in the page is one the *visitor* loads, past every
guard this program owns.  The build still never fails over images; it
just leaves them out.  The content note names the cause:
`large image` for those over `image_cache_max_bytes`, `SVG image` for
`image/svg+xml` (never cached: served from your own origin it could run
scripts), and `image unavailable` for everything else the fetch could
not turn into an image -- an error response, an unreachable or refused
host, or a type outside `IMAGE_EXT`, which covers png, apng, jpeg, gif,
webp, avif, bmp, ico, tiff and heif/heic.  A feed `icon` in any of
those cases falls back to the grey placeholder box.  Nothing about a
failure is recorded, so a later run retries it and a dropped image
comes back on its own; the price is that a build without network egress
loses images instead of falling back to loading them remotely.

The site images the config names -- `output.favicon` and `output.logo`
-- are cached the same way and even without an `images` section, since
those URLs are the operator's own choice rather than feed content: a
remote one is fetched by the build and served from the same origin, and
one it cannot take is dropped with a console warning instead of being
left for the visitor, the HTML falling back to its placeholder box.
There is no content note to carry a site-level image, so that warning
is the only signal.  Local paths in the config are referenced as
written, so the deployment must provide them, and so is a feed `icon`
while image caching is off.  Stylesheets (`output.css`) are the one
remote URL in the config the build never fetches: the visitor loads
those from wherever they point, which is ground you chose yourself.

The SSRF guard blocks non-http(s) schemes and literal private or
loopback addresses and re-checks every redirect hop, but hostnames are
not resolved before connecting: a DNS name pointing at a local address
would therefore still be fetched at build time.  Only the build machine
is exposed that way.  Visitors are exposed neither that way nor any
other, because what the build could not verify is taken out of the page
-- kept remote, a feed could otherwise send every visitor's browser to
`http://192.168.0.1/` and have them probe their own network.

### Security model of the cache

Five separate layers stand between a hostile feed and script running
on your site:

* the sanitizer drops `<svg>` and `<math>` elements whole and notes
  the loss, so inline SVG in feed content never survives (see *Security
  notes*), and its `<script>` body is discarded before that;
* `data:` is not in the URL scheme allow-list, so an SVG cannot be
  inlined as an image source either;
* only the raster types in `imagecache.IMAGE_EXT` are ever written,
  always under hash-derived names, so no cached file is one a browser
  would run;
* SVG is dropped from the post rather than left remote, so visitors
  neither load it from the feed host nor from your own;
* the cache fails closed, so no URL the build could not vouch for ever
  reaches a visitor -- the guard that keeps the *build* from dialing
  private addresses has no say over what a visitor's browser dials.

An SVG needs to be loaded as a *document* -- opened directly, or
framed -- before its scripts run; through `<img>` it renders inert.

**Trusted input.** The cache directory and its `index.json` are read as
trusted input: a deployment restores them from the branch that
published them, and whatever `index.json` names is used without asking
where it came from.  Restore them only from a branch you control --
never from a fork, a pull request, or a cache shared with one.  As
defense in depth, `_trusted_name()` also refuses an index entry whose
extension this writer could not have produced (`.svg`, `.html`, and so
on), which degrades such an entry to an ordinary re-fetch instead of a
same-origin reference.  It is a guard rail, not a sandbox: a cache you
do not control can still serve you wrong bytes.

## Security notes

Feed content is treated as untrusted input.  Feed-supplied HTML in
post summaries is sanitized once at fetch time -- scripts, event
handler attributes and embeds such as `<iframe>` are stripped, and
both the HTML view and the aggregated Atom feed enforce exactly the
same policy.  Embedded content the sanitizer cannot keep at all
(video, audio, graphics such as SVG, forms) is detected by element
type, and both output views then lead the post with a note naming
the dropped elements -- a removed player is never a silent hole.  Every `href`/`src` in summaries and every post link is
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
