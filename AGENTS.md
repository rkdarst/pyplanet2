You don't have access to run Python within the `./venv` environment,
but you can make your own at `~/.venvs`.  You should aim for
simplicity and maintainability, and if some request will greatly
increase complexity out of proportion to the benefit, you should warn
about that before doing it.  The features are flexible.  You should
care about privacy and security.

The way the data flow should go:

1. Load a feed

2. Sanitize to remove all unsafe content.  Add content warnings which
   tell the viewer "some content may have been removed" if it is one
   of the important categories.  Attachments an entry carries outside
   its HTML -- an RSS enclosure or the Atom link with rel="enclosure"
   -- are dropped like any other content the page cannot show and
   named in that warning, as audio, video or attachment; they are
   never fetched and never linked.

3. Resolve all URLs within it (since we are re-publishing it, any
   relative URLs will always be broken).  This applies to images and
   relative links.  A feed configured as a local file path is the one
   exception: it carries no address to resolve against, so its URLs
   stay as written.

4. If image caching is on

    * Try to load every image in the items loaded, including those in the
      posts the output limits will later drop.
    * Images which can't load are dropped with a content warning.
    * Images that are larger than a threshold are dropped.
    * SVG images are never cached: they are dropped from the post.
    * Every fetch goes through the SSRF guard: http(s) only, public
      hosts only, and every redirect hop re-checked.  It covers the
      images a feed names and the config's own favicon and logo.  The
      feed urls themselves are fetched by feedparser, which has no such
      guard: they come from the config, which is trusted input, and a
      visitor loads nothing from them.
	* Images are cached locally and URLs are replaced with these
      images.
	* A cached file is named for a digest of its bytes, so the same
      image from two feeds is stored once and one that changed at the
      same url arrives under a new name.
	* After the caching pass the build prunes the cache: an entry older
      than the TTL that this run did not refer to leaves the index, and
      any file the index no longer names is deleted.  What the output
      links is never deleted, and only names this writer could have
      produced are ever deleted.
	* Remote images in the config.yaml file are also cached -- the
      favicon and the logo even when image caching is off.  Relative
      images there can stay relative.  Stylesheets (output.css) are not
      fetched by the build: the visitor loads them from wherever they
      point.

5. The HTML and Atom views are both updated with the above for
   privacy.

6. Content note added to each post in the HTML view and to each entry
   of the Atom feed, saying some content may have been removed.
