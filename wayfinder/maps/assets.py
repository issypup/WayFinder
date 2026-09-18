"""Bounded map asset caches and streaming image access."""
from collections import OrderedDict
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path
import hashlib
import zipfile

LARGE_MAP_PIXELS = 16_000_000
IMAGE_CACHE_BYTES = 64 * 1024 * 1024

def file_signature(path):
    """Handle file signature."""
    path = Path(path)
    stat = path.stat()
    return (str(path.resolve()), stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)

@lru_cache(maxsize=512)
def _image_hash(signature):
    """Handle image hash."""
    with open(signature[0], 'rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()[:20]

def image_hash(path):
    """Handle image hash."""
    return _image_hash(file_signature(path))

@contextmanager
def open_pack_image(pack, relative):
    """Handle open pack image."""
    from PIL import Image
    relative = relative.replace('\\', '/').lstrip('/')
    if pack.source.is_dir():
        with Image.open(pack.source / relative) as image:
            yield image
    else:
        with zipfile.ZipFile(pack.source) as archive:
            with archive.open(pack.root_prefix + relative) as stream:
                with Image.open(stream) as image:
                    yield image

def image_bytes(image):
    """Handle image bytes."""
    width = image.width() if callable(image.width) else image.width
    height = image.height() if callable(image.height) else image.height
    return width * height * 4

def remember_image(cache, key, image, budget=IMAGE_CACHE_BYTES, max_entries=4):
    """Retain references without duplicating pixel buffers; skip oversized assets."""
    cache.pop(key, None)
    if image_bytes(image) > budget:
        return
    cache[key] = image
    while len(cache) > max_entries or sum(image_bytes(v) for v in cache.values()) > budget:
        cache.pop(next(iter(cache)))

def cached_image(cache, key):
    """Handle cached image."""
    image = cache.pop(key, None)
    if image is not None:
        cache[key] = image
    return image

def render_result(image, zoom):
    """Handle render result."""
    from PIL import Image
    factor = min(1, 184 / image.width, 134 / image.height)
    preview = image.resize((max(1,int(image.width*factor)), max(1,int(image.height*factor))), Image.Resampling.BILINEAR)
    image.info['wayfinder_preview'] = (preview, (image.width * 100 / zoom, image.height * 100 / zoom))
    return ('pil', image)


def asset_key(pack, relative, zoom=None):
    """Handle asset key."""
    source = pack.source / relative if pack.source.is_dir() else pack.source
    try:
        signature = file_signature(source)
    except OSError:
        signature = ("missing",)
    return (str(pack.source), relative, zoom, signature)


class TiledMapPhoto:
    """Own bounded Tk image strips without allocating a second full-size image."""
    def __init__(self, width, height, preview=None):
        """Handle init."""
        self._width = width
        self._height = height
        self.wayfinder_preview = preview
        self.tiles = []

    def width(self):
        """Handle width."""
        return self._width

    def height(self):
        """Handle height."""
        return self._height


def draw_map_photo(canvas, photo):
    """Handle draw map photo."""
    if isinstance(photo, TiledMapPhoto):
        for y, strip in photo.tiles:
            canvas.create_image(0, y, image=strip, anchor="nw", tags=("map_image",))
    else:
        canvas.create_image(0, 0, image=photo, anchor="nw", tags=("map_image",))
