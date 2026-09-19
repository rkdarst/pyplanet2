"""Local image caching for pyplanet2.

Downloads images referenced by feed items (post <img> sources and feed
icons) into a directory that doubles as cache and deploy output, and
rewrites the references to the local copies.  Visitors then never load
images from the feed hosts (privacy), posts survive upstream link rot,
and repeat runs are cheap: entries younger than ttl_days are not
touched at all, older ones are revalidated with a conditional request
that transfers nothing when the image is unchanged.

Safety rules: only http(s) URLs; no localhost/private-IP hosts;
images over the size cap (default 10 MB) are dropped from the
output and listed as "large image" instead of being left pointing at
the remote host (visitor requests would leak there); the response
must be an image/* content type; and file names are pure content-hash-derived, so no URL can ever
escape the cache directory.  image/svg+xml is deliberately not
localized: an SVG served from your own origin could run scripts.
Anything that fails keeps its original remote URL, so the build never
breaks on images.
"""
import hashlib
import ipaddress
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

IMAGE_EXT = {
    "image/png": "png", "image/apng": "png", "image/jpeg": "jpg",
    "image/gif": "gif", "image/webp": "webp", "image/avif": "avif",
    "image/bmp": "bmp", "image/x-icon": "ico",
    "image/vnd.microsoft.icon": "ico",
}
SRC_ATTR_RE = re.compile(r'src="([^"]*)"')
# Only hash-derived file names are ever trusted from the cache index.
SAFE_NAME_RE = re.compile(r"\A[0-9a-f]{16}\.[a-z0-9]{1,5}\Z")
USER_AGENT = "pyplanet2/1.0 (blog aggregator)"


class ImageTooLarge(ValueError):
    """Raised by fetchers when a response exceeds max_bytes."""


def is_http_url(url):
    return urlparse(url).scheme.lower() in ("http", "https")


def _private_host(host):
    """True for localhost/private/reserved hosts (SSRF guard)."""
    if not host:
        return True
    host = host.rstrip(".").lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        return True
    if "." not in host:
        return True  # would resolve via local search domains
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (ip.is_private or ip.is_loopback or ip.is_link_local
            or ip.is_reserved or ip.is_unspecified)


def _check_public_http(url):
    parts = urlparse(url)
    if parts.scheme.lower() not in ("http", "https"):
        raise ValueError(f"refusing non-http(s) URL: {url!r}")
    if _private_host(parts.hostname):
        raise ValueError(f"refusing private host: {url!r}")


class _SafeRedirect(HTTPRedirectHandler):
    """Follow redirects only to public http(s) URLs."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        try:
            _check_public_http(newurl)
        except ValueError:
            raise HTTPError(newurl, code, "redirect to unsafe URL", None, fp)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def make_urllib_fetcher(timeout=15, max_bytes=10 * 1024 * 1024):
    """Default fetcher: fetcher(url, headers) -> (status, body, headers).

    Response header keys are lower-cased; body is empty for 304s.
    """
    opener = build_opener(_SafeRedirect())

    def fetch(url, headers):
        _check_public_http(url)
        request = Request(url, headers={"User-Agent": USER_AGENT, **headers})
        try:
            with opener.open(request, timeout=timeout) as resp:
                body = resp.read(max_bytes + 1)
                status = resp.status
                resp_headers = {k.lower(): v for k, v in resp.headers.items()}
        except HTTPError as err:
            if err.code == 304:
                return 304, b"", {k.lower(): v for k, v in err.headers.items()}
            raise
        if len(body) > max_bytes:
            raise ImageTooLarge(f"image exceeds {max_bytes} bytes: {url}")
        return status, body, resp_headers

    return fetch


def _paths(file_name, dir_name, base_url):
    return {"html": f"{dir_name}/{file_name}",
            "atom": f"{base_url}/{dir_name}/{file_name}"}


def load_index(cache_dir):
    try:
        return json.loads((cache_dir / "index.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}


def save_index(cache_dir, index):
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / "index.tmp"
    tmp.write_text(json.dumps(index, indent=1, sort_keys=True), "utf-8")
    tmp.replace(cache_dir / "index.json")


def _fresh_paths(entry, cache_dir, dir_name, base_url, now, ttl):
    """Cached paths when the entry is complete and within its TTL."""
    file_name = entry.get("file", "")
    if not SAFE_NAME_RE.match(file_name) or not (cache_dir / file_name).is_file():
        return None
    try:
        fetched = datetime.fromisoformat(entry["fetched_at"])
        if now - fetched > ttl:
            return None
    except (KeyError, TypeError, ValueError):
        return None
    return _paths(file_name, dir_name, base_url)


def _reusable(entry, cache_dir):
    file_name = entry.get("file", "")
    if SAFE_NAME_RE.match(file_name) and (cache_dir / file_name).is_file():
        return file_name
    return None


def _fetch_into_cache(url, index, cache_dir, dir_name, base_url, now, fetcher):
    entry = index.get(url) or {}
    headers = {}
    if entry.get("etag"):
        headers["If-None-Match"] = entry["etag"]
    if entry.get("last_modified"):
        headers["If-Modified-Since"] = entry["last_modified"]
    try:
        status, body, resp_headers = fetcher(url, headers)
    except ImageTooLarge:
        raise  # caller drops the image and flags the post
    except Exception:
        return None
    now_iso = now.isoformat(timespec="seconds")
    if status == 304:
        file_name = _reusable(entry, cache_dir)
        if not file_name:
            return None
        index.setdefault(url, {})["fetched_at"] = now_iso
        return _paths(file_name, dir_name, base_url)
    if status != 200:
        return None
    content_type = (resp_headers.get("content-type") or "").split(";")[0]
    content_type = content_type.strip().lower()
    ext = IMAGE_EXT.get(content_type)  # also drops svg and unknown types
    if not ext:
        return None
    file_name = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16] + "." + ext
    cache_dir.mkdir(parents=True, exist_ok=True)
    tmp = cache_dir / (file_name + ".part")
    tmp.write_bytes(body)
    tmp.replace(cache_dir / file_name)
    index[url] = {"file": file_name, "etag": resp_headers.get("etag"),
                  "last_modified": resp_headers.get("last-modified"),
                  "fetched_at": now_iso}
    return _paths(file_name, dir_name, base_url)


def drop_large_images(items, large_urls):
    """Remove img tags for too-large images and flag the posts.

    Flagged posts list "large image" in removed_content, so both
    output views note it; a too-large feed icon falls back to the
    placeholder box.
    """
    for item in items:
        summary = item.get("summary") or ""
        lost = False
        for url in large_urls:
            summary, hits = re.subn(
                f'<img[^>]*src="{re.escape(url)}"[^>]*>', "", summary)
            lost = lost or bool(hits)
        if item.get("icon") in large_urls:
            item["icon"] = ""
            lost = True
        if lost:
            item["removed_content"] = sorted(
                set(item.get("removed_content") or []) | {"large image"})
        item["summary"] = summary


def localize_images(items, config, fetcher=None):
    """Download all item images into the cache dir and attach img_map.

    items get an "img_map" ({url: {"html": rel, "atom": abs}}) used by
    the generators via rewrite_images(), and localized feed icons are
    rewritten in place (icons only appear in the HTML view).
    """
    imgcfg = config.get("images") or {}
    dir_name = str(imgcfg.get("dir", "images")).rstrip("/")
    cache_dir = Path(dir_name)
    ttl = timedelta(days=imgcfg.get("ttl_days", 1))
    base_url = str(imgcfg.get("base_url")
                   or config["site"]["site_url"]).rstrip("/")
    if fetcher is None:
        fetcher = make_urllib_fetcher(imgcfg.get("timeout", 15),
                                      imgcfg.get("image_cache_max_bytes",
                                      10 * 1024 * 1024))
    now = datetime.now(timezone.utc)
    index = load_index(cache_dir)

    urls = set()
    for item in items:
        urls.update(u for u in SRC_ATTR_RE.findall(item.get("summary") or "")
                    if is_http_url(u))
        if is_http_url(item.get("icon") or ""):
            urls.add(item["icon"])

    mapping = {}
    large_urls = set()
    for url in sorted(urls):
        entry = index.get(url) or {}
        paths = _fresh_paths(entry, cache_dir, dir_name, base_url, now, ttl)
        if paths is None:
            try:
                paths = _fetch_into_cache(url, index, cache_dir, dir_name,
                                          base_url, now, fetcher)
            except ImageTooLarge:
                # Too big to cache; leaving it remote would leak
                # visitor requests, so it gets dropped instead.
                large_urls.add(url)
        if paths is not None:
            mapping[url] = paths

    if large_urls:
        drop_large_images(items, large_urls)

    if urls:
        save_index(cache_dir, index)
    if mapping:
        for item in items:
            item["img_map"] = mapping
            icon = item.get("icon") or ""
            if icon in mapping:
                item["icon"] = mapping[icon]["html"]
    return mapping


def rewrite_images(text, img_map, kind):
    """Point img sources at cached copies ("html" relative/"atom" absolute)."""
    if not text or not img_map:
        return text
    for url, paths in img_map.items():
        text = text.replace(f'src="{url}"', f'src="{paths[kind]}"')
    return text
