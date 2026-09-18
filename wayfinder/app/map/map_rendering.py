"""Provide map rendering support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

from .map_shared import *

class MapRenderingMixin:
    """Map subsystem responsibilities extracted from MapPageMixin."""
    def _map_render_worker_loop(self):
        """Single producer-consumer worker for all expensive map image work."""
        while True:
            with self._map_render_condition:
                while self._map_render_pending is None and not self._closing:
                    self._map_render_condition.wait()
                if self._closing:
                    return
                # Variable(s): `request` (request); named state retained for the surrounding calculation or subsequent calls.
                request = self._map_render_pending
                self._map_render_pending = None
            # Variable(s): `generation` (generation), `key` (key), `pack` (pack), `md` (metadata), `zoom` (zoom), `old_x` (old x); named state retained for the surrounding calculation or subsequent calls.
            generation,key,pack,md,zoom,old_x,old_y,preserve_view = request
            if self._closing or generation != self.map_render_generation:
                continue
            published = False
            if not hasattr(self,"_map_performance_ms"):
                self._map_performance_ms={}
            render_started=time.perf_counter()
            try:
                # Variable(s): `source_key` (source key); named state retained for the surrounding calculation or subsequent calls.
                source_key=asset_key(pack,md.image)
                if Image is None:
                    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
                    raw=pack.read_bytes(md.image)
                    # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
                    result=("tkraw",raw)
                else:
                    # Variable(s): `disk_cached` (disk cached); named state retained for the surrounding calculation or subsequent calls.
                    cache_lookup_started=time.perf_counter()
                    disk_cached = cached_map_path(pack.source, md.image, zoom) if pack.source.is_dir() else None
                    with self._map_scaled_cache_lock:
                        # Variable(s): `decoded` (decoded); named state retained for the surrounding calculation or subsequent calls.
                        decoded=cached_image(self.map_scaled_cache,key)
                        # Variable(s): `img` (image); named state retained for the surrounding calculation or subsequent calls.
                        img=decoded
                    if img is None and disk_cached is not None and disk_cached.is_file():
                        try:
                            # Variable(s): `cached_img` (cached img); named state retained for the surrounding calculation or subsequent calls.
                            with Image.open(disk_cached) as cached_img:
                                cached_img.verify()
                            # Variable(s): `cached_img` (cached img); named state retained for the surrounding calculation or subsequent calls.
                            with Image.open(disk_cached) as cached_img:
                                # Variable(s): `img` (image); named state retained for the surrounding calculation or subsequent calls.
                                img = cached_img.convert("RGBA")
                        except Exception:
                            try: disk_cached.unlink(missing_ok=True)
                            except OSError: _ignored("intentional best-effort fallback")
                            # Variable(s): `img` (image); named state retained for the surrounding calculation or subsequent calls.
                            img=None
                        if img is not None:
                            self._last_map_cache_detail="disk cache hit"
                            with self._map_scaled_cache_lock:
                                remember_image(self.map_scaled_cache,key,img)
                    if img is not None:
                        self._map_performance_ms["scale_cache"]=round((time.perf_counter()-cache_lookup_started)*1000.0,3)
                        # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
                        result=render_result(img,zoom)
                        if not self._closing and generation == self.map_render_generation:
                            self.events.put(("map_render_done", (generation,key,result,old_x,old_y,preserve_view)))
                        continue
                    with self._map_source_cache_lock:
                        # Variable(s): `cached_source` (cached source); named state retained for the surrounding calculation or subsequent calls.
                        cached_source=cached_image(self.map_source_cache,source_key)
                        # Variable(s): `img` (image); named state retained for the surrounding calculation or subsequent calls.
                        img=cached_source
                    if img is None:
                        decode_started=time.perf_counter()
                        # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
                        with open_pack_image(pack, md.image) as opened:
                            img=opened.convert("RGBA")
                        self._map_performance_ms["source_decode"]=round((time.perf_counter()-decode_started)*1000.0,3)
                        self._last_map_cache_detail="loaded from map pack"
                    elif cached_source is not None:
                        self._last_map_cache_detail="memory source cache hit"
                        with self._map_source_cache_lock:
                            remember_image(self.map_source_cache,source_key,img, budget=384 * 1024 * 1024, max_entries=2)
                    # If a newer request appeared while decoding, skip this resize entirely.
                    with self._map_render_condition:
                        # Variable(s): `superseded` (superseded); named state retained for the surrounding calculation or subsequent calls.
                        superseded = self._map_render_pending is not None and self._map_render_pending[0] > generation
                    if superseded or self._closing or generation != self.map_render_generation:
                        continue
                    # Variable(s): `factor` (factor); named state retained for the surrounding calculation or subsequent calls.
                    factor=zoom/100.0
                    # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
                    target=(max(1,int(img.width*factor)),max(1,int(img.height*factor)))
                    scale_started=time.perf_counter()
                    if target != img.size:
                        # Variable(s): `img` (image); named state retained for the surrounding calculation or subsequent calls.
                        img=img.resize(target, Image.Resampling.BILINEAR)
                    self._map_performance_ms["scale_cache"]=round((time.perf_counter()-scale_started)*1000.0,3)
                    # Variable(s): `result` (result); named state retained for the surrounding calculation or subsequent calls.
                    with self._map_scaled_cache_lock:
                        remember_image(self.map_scaled_cache,key,img)
                    if pack.source.is_dir():
                        persist_zoom_image_async(pack.source, md.image, zoom, img)
                    result=render_result(img,zoom)
                    # Publish immediately; interactive rendering never writes PNGs.
                    if not self._closing and generation == self.map_render_generation:
                        self.events.put(("map_render_done", (generation,key,result,old_x,old_y,preserve_view)))
                        published = True
                    # Persistent views are prepared by pack installation. Never
                    # compress PNGs on the interactive render worker: that blocks
                    # the next requested map even after this result is displayed.
                if not published and not self._closing and generation == self.map_render_generation:
                    self.events.put(("map_render_done", (generation,key,result,old_x,old_y,preserve_view)))
            except Exception as exc:
                if not self._closing:
                    self.events.put(("map_render_failed", (generation, exc)))

    def _prefetch_neighbor_zoom_images(self, pack, md, zoom, generation):
        """Decode nearby persistent zoom-cache images while the user is viewing the current level."""
        if Image is None or not pack.source.is_dir() or self._closing:
            return
        # Variable(s): `levels` (levels); named state retained for the surrounding calculation or subsequent calls.
        with open_pack_image(pack, md.image) as header:
            if header.width * header.height >= LARGE_MAP_PIXELS:
                return
        levels=list(ZOOM_CACHE_LEVELS)
        # Variable(s): `idx` (index); named state retained for the surrounding calculation or subsequent calls.
        try: idx=levels.index(int(zoom))
        except ValueError: return
        # Variable(s): `neighbors` (neighbors); named state retained for the surrounding calculation or subsequent calls.
        neighbors=[]
        if idx+1 < len(levels): neighbors.append(levels[idx+1])
        if idx-1 >= 0: neighbors.append(levels[idx-1])
        # Loop variable(s): `nearby` (nearby); each iteration represents the next value from the iterable below.
        for nearby in neighbors:
            with self._map_render_condition:
                if self._closing or (self._map_render_pending is not None and self._map_render_pending[0] > generation):
                    return
            # Variable(s): `nearby_key` (nearby key); named state retained for the surrounding calculation or subsequent calls.
            nearby_key=asset_key(pack,md.image,nearby)
            with self._map_scaled_cache_lock:
                if nearby_key in self.map_scaled_cache:
                    continue
            # Variable(s): `path` (path); named state retained for the surrounding calculation or subsequent calls.
            path=cached_map_path(pack.source, md.image, nearby)
            if not path.is_file():
                continue
            try:
                # Variable(s): `cached_img` (cached img); named state retained for the surrounding calculation or subsequent calls.
                with Image.open(path) as cached_img:
                    # Variable(s): `decoded` (decoded); named state retained for the surrounding calculation or subsequent calls.
                    if cached_img.width * cached_img.height * 4 > 64 * 1024 * 1024:
                        continue
                    decoded=cached_img.convert("RGBA")
                with self._map_scaled_cache_lock:
                    remember_image(self.map_scaled_cache,nearby_key,decoded)
            except Exception:
                return

    def _prefetch_adjacent_maps(self, pack, md, zoom, generation):
        """Warm the likely previous/next map images while Tk is idle.

        This is intentionally conservative: only immediate neighbours in the pack
        order are considered, no Tk objects are created off-thread, and a newer
        render generation cancels the work before another decode begins.
        """
        if Image is None or self._closing or not pack or not md:
            return
        try:
            ordered=list(pack.maps)
            index=next(i for i,row in enumerate(ordered) if row.name==md.name)
        except Exception:
            return
        candidates=[]
        if index+1 < len(ordered): candidates.append(ordered[index+1])
        if index-1 >= 0: candidates.append(ordered[index-1])
        if not candidates:
            return
        def worker():
            """Handle worker."""
            for candidate in candidates:
                if self._closing or generation != self.map_render_generation:
                    return
                key=asset_key(pack,candidate.image,int(zoom))
                with self._map_scaled_cache_lock:
                    if key in self.map_scaled_cache:
                        continue
                img=None
                path=cached_map_path(pack.source,candidate.image,int(zoom)) if pack.source.is_dir() else None
                if path is not None and path.is_file():
                    try:
                        with Image.open(path) as opened:
                            img=opened.convert("RGBA")
                    except Exception:
                        img=None
                if img is None:
                    try:
                        with open_pack_image(pack,candidate.image) as opened:
                            source=opened.convert("RGBA")
                        factor=int(zoom)/100.0
                        target=(max(1,int(source.width*factor)),max(1,int(source.height*factor)))
                        img=source if target==source.size else source.resize(target,Image.Resampling.BILINEAR)
                    except Exception:
                        continue
                with self._map_scaled_cache_lock:
                    remember_image(self.map_scaled_cache,key,img)
                if pack.source.is_dir():
                    persist_zoom_image_async(pack.source,candidate.image,int(zoom),img)
        threading.Thread(target=worker,name="WayFinder-Map-Predictive-Prefetch",daemon=True).start()

    def _render_map(self, preserve_view=False):
        """Queue the latest map background request for the single render worker."""
        if self._closing or not hasattr(self,"map_canvas"): return
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        pack=self.active_map_pack; md=self._current_map_def()
        if pack and md:
            self._map_render_started_at=time.perf_counter()
            if hasattr(self,"map_load_strip"):
                self.map_load_strip.set(f"Loading {md.title} · {int(self.map_zoom.get())}% · {getattr(self,'_last_map_cache_detail','checking cache')} · preparing {len(getattr(pack,'markers',[]) or [])} markers")
        if not pack or not md:
            self.map_rendering_key = None
            for progress in (getattr(self, 'map_render_progress', None), getattr(self, '_map_popout_render_progress', None)):
                if progress is not None: progress.stop()
            self.map_canvas.delete("all")
            self._map_marker_items.clear(); self._map_marker_visual_state.clear(); self._map_marker_layout_key=None
            return
        # Variable(s): `old_x` (old x); named state retained for the surrounding calculation or subsequent calls.
        old_x=self.map_canvas.xview()[0] if preserve_view else 0.0
        # Variable(s): `old_y` (old y); named state retained for the surrounding calculation or subsequent calls.
        old_y=self.map_canvas.yview()[0] if preserve_view else 0.0
        # Variable(s): `zoom` (zoom); named state retained for the surrounding calculation or subsequent calls.
        zoom=int(self.map_zoom.get()); key=asset_key(pack,md.image,zoom)
        if self.map_rendering_key == key:
            return
        # Variable(s): `cached` (cached); named state retained for the surrounding calculation or subsequent calls.
        cached=cached_image(self.map_photo_cache,key)
        if cached is not None:
            self._last_map_cache_detail="memory cache hit"
            if self._world_preparation_complete:
                self._world_preparation_complete["map_cache"]=self._last_map_cache_detail; self._update_preparation_panel()
            preview=getattr(cached,"wayfinder_preview",None)
            if preview is not None:
                self._map_preview=(key,preview)
            self._apply_map_photo(key,cached,old_x,old_y,preserve_view)
            return
        self.map_render_generation += 1
        # Variable(s): `generation` (generation); named state retained for the surrounding calculation or subsequent calls.
        generation=self.map_render_generation
        self.map_rendering_key=key
        self.map_status.set(f"Loading {md.title} at {zoom}%…")
        with self._map_render_condition:
            self._map_render_pending=(generation,key,pack,md,zoom,old_x,old_y,preserve_view)
            self._map_render_condition.notify()

    def _finish_map_render(self,generation,key,result,old_x,old_y,preserve_view):
        """Handle finish map render."""
        tk_upload_started=time.perf_counter()
        if generation != self.map_render_generation or key != self.map_rendering_key:
            return
        if getattr(self,"_world_preparation_complete",None):
            self._world_preparation_complete["map_cache"]=getattr(self,"_last_map_cache_detail","loaded")
            self._update_preparation_panel()
        # Variable(s): `kind` (kind), `data` (data); named state retained for the surrounding calculation or subsequent calls.
        kind,data=result
        try:
            if kind=="pil" and ImageTk is not None:
                # Variable(s): `photo` (photo); named state retained for the surrounding calculation or subsequent calls.
                preview=data.info.get("wayfinder_preview")
                if preview is not None:
                    self._map_preview=(key,preview)
                if data.width * data.height > 4_000_000:
                    self._upload_map_photo(generation,key,data,old_x,old_y,preserve_view)
                    return
                photo=ImageTk.PhotoImage(data,master=self.root)
                photo.wayfinder_preview=preview
            else:
                # Variable(s): `photo` (photo); named state retained for the surrounding calculation or subsequent calls.
                photo=tk.PhotoImage(data=base64.b64encode(data),master=self.root)
                # Variable(s): `zoom` (zoom); named state retained for the surrounding calculation or subsequent calls.
                zoom=key[2]
                # Variable(s): `photo` (photo); named state retained for the surrounding calculation or subsequent calls.
                if zoom==25: photo=photo.subsample(4,4)
                # Variable(s): `photo` (photo); named state retained for the surrounding calculation or subsequent calls.
                elif zoom==50: photo=photo.subsample(2,2)
                # Variable(s): `photo` (photo); named state retained for the surrounding calculation or subsequent calls.
                elif zoom==200: photo=photo.zoom(2,2)
            remember_image(self.map_photo_cache,key,photo)
            self._map_performance_ms["tk_upload"]=round((time.perf_counter()-tk_upload_started)*1000.0,3)
            self._apply_map_photo(key,photo,old_x,old_y,preserve_view)
        except Exception as exc:
            self._map_render_failed(generation,exc)

    def _upload_map_photo(self,generation,key,data,old_x,old_y,preserve_view):
        """Transfer large images to Tk in bounded strips, yielding between strips."""
        if not hasattr(self,"_map_performance_ms"):
            self._map_performance_ms={}
        upload_started=time.perf_counter()
        photo=TiledMapPhoto(data.width,data.height,data.info.get("wayfinder_preview"))
        rows=max(1,min(256,1_000_000//data.width))

        def upload(y=0):
            """Handle upload."""
            nonlocal photo, data
            if self._closing or generation != self.map_render_generation or key != self.map_rendering_key:
                photo = data = None
                return
            try:
                end=min(data.height,y+rows)
                strip=ImageTk.PhotoImage(data.crop((0,y,data.width,end)),master=self.root)
                photo.tiles.append((y,strip))
                if end < data.height:
                    self.root.after(1,upload,end)
                else:
                    remember_image(self.map_photo_cache,key,photo)
                    self._map_performance_ms["tk_upload"]=round((time.perf_counter()-upload_started)*1000.0,3)
                    self._apply_map_photo(key,photo,old_x,old_y,preserve_view)
                    photo = data = None
            except Exception as exc:
                photo = data = None
                self._map_render_failed(generation,exc)
        self.root.after(1,upload)

    def _apply_map_photo(self,key,photo,old_x,old_y,preserve_view):
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        """Handle apply map photo."""
        pack=self.active_map_pack; md=self._current_map_def()
        if not pack or not md or key != asset_key(pack,md.image,int(self.map_zoom.get())):
            return
        self.map_photo=photo; self.map_background_key=key; self.map_rendering_key=None
        # Swap the background only after the new zoom/map image is fully ready.
        # The previous render remains visible throughout preparation.
        self.map_canvas.delete("map_image")
        draw_map_photo(self.map_canvas,photo)
        self.map_canvas.tag_lower("map_image")
        self._map_marker_visual_state.clear()
        self.map_canvas.configure(scrollregion=(0,0,photo.width(),photo.height()))
        # Marker rebuilding can create thousands of Canvas primitives.  Yield back to Tk
        # after the new background is attached so zoom never holds the GUI hostage while
        # the background worker has already finished its expensive image work.
        self.root.after_idle(lambda: self._refresh_map_markers(force_rebuild=True) if not self._closing else None)
        self.root.after_idle(self._refresh_popout_map)
        if hasattr(self,"map_render_progress"):
            try: self.map_render_progress.stop()
            except tk.TclError: _ignored("intentional best-effort fallback")
        if self._map_popout_render_progress is not None:
            try: self._map_popout_render_progress.stop()
            except tk.TclError: _ignored("intentional best-effort fallback")
        # Variable(s): `anchor` (anchor); named state retained for the surrounding calculation or subsequent calls.
        anchor=self._map_zoom_anchor
        if anchor and anchor[4] == int(self.map_zoom.get()):
            # Variable(s): `base_x` (base x), `base_y` (base y), `screen_x` (screen x), `screen_y` (screen y), `_zoom` (zoom); named state retained for the surrounding calculation or subsequent calls.
            base_x,base_y,screen_x,screen_y,_zoom=anchor
            # Variable(s): `left` (left); named state retained for the surrounding calculation or subsequent calls.
            left=max(0.0,base_x*(int(self.map_zoom.get())/100.0)-screen_x)
            # Variable(s): `top` (top); named state retained for the surrounding calculation or subsequent calls.
            top=max(0.0,base_y*(int(self.map_zoom.get())/100.0)-screen_y)
            self.map_canvas.xview_moveto(left/max(1,photo.width()))
            self.map_canvas.yview_moveto(top/max(1,photo.height()))
            self._map_zoom_anchor=None
        elif preserve_view:
            self.map_canvas.xview_moveto(old_x); self.map_canvas.yview_moveto(old_y)
        else:
            # Variable(s): `remembered` (remembered); named state retained for the surrounding calculation or subsequent calls.
            remembered=self._restore_map_view(pack, md)
            if remembered:
                self.map_canvas.xview_moveto(max(0.0,min(1.0,remembered[0])))
                self.map_canvas.yview_moveto(max(0.0,min(1.0,remembered[1])))
        self._last_map_render_seconds=max(0.0,time.perf_counter()-float(getattr(self,"_map_render_started_at",time.perf_counter()) or time.perf_counter()))
        self.map_status.set(f"{md.title} • {int(self.map_zoom.get())}% • middle-drag to pan • Home fits map")
        if hasattr(self,"map_load_strip"):
            self.map_load_strip.set(f"{md.title} · {int(self.map_zoom.get())}% · {len(getattr(pack,'markers',[]) or [])} markers · {getattr(self,'_last_map_cache_detail','loaded')}")
        self._update_diagnostic_timings()
        generation=self.map_render_generation
        self.root.after(300,lambda:self._prefetch_adjacent_maps(pack,md,int(self.map_zoom.get()),generation) if not self._closing and self.map_background_key==key else None)

        # Auto-enlarge only small source maps after an explicit map change.
        # Large maps retain the user's chosen zoom, so existing packs keep
        # their current behaviour.  This is particularly useful for compact
        # World Map/overview images embedded alongside full-size area maps.
        if getattr(self, "_map_auto_fit_small_pending", False):
            self._map_auto_fit_small_pending = False
            # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
            current=max(1, int(self.map_zoom.get())) / 100.0
            # Variable(s): `base_w` (base w); named state retained for the surrounding calculation or subsequent calls.
            base_w=max(1.0, photo.width() / current)
            # Variable(s): `base_h` (base h); named state retained for the surrounding calculation or subsequent calls.
            base_h=max(1.0, photo.height() / current)
            # Variable(s): `view_w` (view w); named state retained for the surrounding calculation or subsequent calls.
            view_w=max(1, self.map_canvas.winfo_width()-4)
            # Variable(s): `view_h` (view h); named state retained for the surrounding calculation or subsequent calls.
            view_h=max(1, self.map_canvas.winfo_height()-4)
            # Only intervene when the source image itself is notably smaller
            # than the viewport.  Never auto-shrink normal/large maps.
            if base_w < view_w * 0.80 and base_h < view_h * 0.80:
                # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
                target=100.0*min(view_w/base_w, view_h/base_h)
                # Variable(s): `levels` (levels); named state retained for the surrounding calculation or subsequent calls.
                levels=ZOOM_CACHE_LEVELS
                # Variable(s): `chosen` (chosen); named state retained for the surrounding calculation or subsequent calls.
                chosen=max((z for z in levels if z <= target), default=min(levels))
                # Variable(s): `chosen` (chosen); named state retained for the surrounding calculation or subsequent calls.
                chosen=max(100, chosen)
                if chosen > int(self.map_zoom.get()):
                    self.map_zoom.set(chosen)
                    self._request_map_render(preserve_view=False, delay=20)

    def _map_render_failed(self,generation,exc):
        """Handle map render failed."""
        if generation != self.map_render_generation or self.map_rendering_key is None: return
        self._map_failed_key = self.map_rendering_key
        self.map_rendering_key=None
        if hasattr(self,"map_render_progress"):
            try: self.map_render_progress.stop()
            except tk.TclError: _ignored("intentional best-effort fallback")
        if self._map_popout_render_progress is not None:
            try: self._map_popout_render_progress.stop()
            except tk.TclError: _ignored("intentional best-effort fallback")
        # Variable(s): `md` (metadata); named state retained for the surrounding calculation or subsequent calls.
        md=self._current_map_def()
        self.map_status.set(f"Could not render {md.title if md else 'map'}: {exc}")
        self._append_log(f"Map render failed: {exc}")

