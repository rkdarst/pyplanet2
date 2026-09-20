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
   of the important categories.

3. Resolve all URLs within it (since we are re-publishing it, any
   relative URLs will always be broken).  This applies to images and
   relative links.

4. If image caching is on

	* Try to load all images.
	* Images which can't load are dropped with a content warning.
	* Images that are larger than a threshold are dropped.
	* SVG images are never cached: they are dropped from the post.
	* Images are cached locally and URLs are replaced with these
      images.
	* Remote images in the config.yaml file are also cached -- the
      favicon and the logo even when image caching is off.  Relative
      images there can stay relative.  Stylesheets (output.css) are not
      fetched by the build: the visitor loads them from wherever they
      point.

5. The HTML and Atom views are both updated with the above for
   privacy.

6. Content note added to each post in the HTML view and to each entry
   of the Atom feed, saying some content may have been removed.
