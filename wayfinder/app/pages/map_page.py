"""Provide map page support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

from ..map.map_shared import *
from ..map.map_rendering import MapRenderingMixin
from ..map.map_markers import MapMarkersMixin
from ..map.map_interactions import MapInteractionsMixin
from ..map.map_navigation import MapNavigationMixin
from ..map.map_popout import MapPopoutMixin
from ..map.map_routes import MapRoutesMixin

class MapPageMixin(
    MapRenderingMixin,
    MapMarkersMixin,
    MapInteractionsMixin,
    MapNavigationMixin,
    MapPopoutMixin,
    MapRoutesMixin,
):
    """Map page composition and top-level map state refresh callbacks."""
    def _build_map(self):
        """Build the WayFinder map-pack viewer."""
        # Variable(s): `p` (p); named state retained for the surrounding calculation or subsequent calls.
        p=self._page("Map")
        # Variable(s): `h` (height/handle value (context dependent)); named state retained for the surrounding calculation or subsequent calls.
        h=ttk.Frame(p); h.pack(fill="x",pady=(4,6)); ttk.Label(h,text="Map",style="Title.TLabel").pack(side="left")
        ttk.Button(h,text="←",width=3,command=self._map_history_back).pack(side="left",padx=(10,2)); ttk.Button(h,text="→",width=3,command=self._map_history_forward).pack(side="left",padx=2); ttk.Button(h,text="Pop out",command=self._popout_map).pack(side="left",padx=(6,0))
        ttk.Label(h,text="Variant",style="Muted.TLabel").pack(side="left",padx=(12,3))
        self.map_variant_selector=ttk.Combobox(h,textvariable=self.map_variant_choice,state="disabled",width=24,values=("Auto",),style="MapName.TCombobox")
        self.map_variant_selector.pack(side="left",padx=(0,4)); self.map_variant_selector.bind("<<ComboboxSelected>>",self._map_variant_selected)
        ttk.Button(h,text="+",width=3,command=lambda:self._change_map_zoom(1)).pack(side="right")
        self.map_zoom_box=ttk.Combobox(h,textvariable=self.map_zoom,state="readonly",width=7,values=ZOOM_CACHE_LEVELS); self.map_zoom_box.pack(side="right",padx=4); self.map_zoom_box.bind("<<ComboboxSelected>>",lambda _e:self._request_map_render(preserve_view=True))
        ttk.Button(h,text="−",width=3,command=lambda:self._change_map_zoom(-1)).pack(side="right")
        ttk.Button(h,text="100%",width=5,command=self._map_reset_zoom).pack(side="right",padx=(6,0))
        ttk.Button(h,text="Fit",width=4,command=self._map_fit_zoom).pack(side="right",padx=(4,0))
        ttk.Label(h,text="Zoom",style="Muted.TLabel").pack(side="right",padx=(6,2))
        self.map_selector_var=tk.StringVar(); self.map_selector=ttk.Combobox(h,textvariable=self.map_selector_var,state="readonly",width=24,style="MapName.TCombobox"); self.map_selector.pack(side="right",padx=6); self.map_selector.bind("<<ComboboxSelected>>",self._map_selected_by_user)

        # The selected map is the user's current viewing area.  Keep this UI
        # separate from runtime ``area_summary`` names because map-pack titles
        # and APWorld region names are not guaranteed to be identical.
        self.map_current_area=tk.StringVar(value="Current area: —")
        ttk.Label(p,textvariable=self.map_current_area,style="CardValue.TLabel").pack(anchor="w",pady=(0,3))

        # A segmented 0-100% bar represents *every generated check on the
        # selected map*.  Segment width is proportional to the number of checks
        # in each canonical state, so grouped markers contribute all of their
        # real AP locations rather than one visual marker.
        palette=self._palette()
        self.map_area_progress_canvas=tk.Canvas(p,height=24,highlightthickness=1,highlightbackground=palette.get("border", palette["accent_soft"]),bg=palette["card"])
        self.map_area_progress_canvas.pack(fill="x",pady=(0,2))
        self.map_area_progress_canvas.bind("<Configure>",lambda _e:self._draw_current_area_progress())
        self.map_area_progress_scale=tk.StringVar(value="0%                                                                 100%")
        ttk.Label(p,textvariable=self.map_area_progress_scale,style="Muted.TLabel",justify="left").pack(fill="x")
        self.map_area_progress_detail=tk.StringVar(value="No checks on selected map")
        ttk.Label(p,textvariable=self.map_area_progress_detail,style="Muted.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(0,5))

        self.map_load_strip=tk.StringVar(value="Map idle")
        ttk.Label(p,textvariable=self.map_load_strip,style="CardValue.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(0,3))
        self.map_status=tk.StringVar(value=f"No compatible map pack selected. Install packs to {default_pack_dir()} or open Installed Maps to install one")
        ttk.Label(p,textvariable=self.map_status,style="Muted.TLabel",wraplength=1050,justify="left").pack(anchor="w",pady=(0,3))
        # Rendering indicator is deliberately indeterminate: Pillow decode/resize/cache work runs
        # in the map worker and does not expose meaningful byte-level progress.
        self.map_render_progress=ttk.Progressbar(p,mode="indeterminate",length=220)
        self.map_render_progress.pack(fill="x",pady=(0,5))
        self.map_render_progress.stop()

        # Map legend and controls are intentionally presented as separate cards:
        # the legend answers "what does this colour mean?" while controls answer
        # "how should the map behave?".  Keeping those concerns visually
        # distinct makes the dense map toolbar much easier to scan.
        controls=ttk.Frame(p)
        controls.pack(fill="x",pady=(0,8))
        controls.columnconfigure(0,weight=3)
        controls.columnconfigure(1,weight=2)

        palette=self._palette()
        legend=ttk.Frame(controls,style="Card.TFrame",padding=(12,10))
        legend.grid(row=0,column=0,sticky="nsew",padx=(0,6))
        legend_header=ttk.Frame(legend,style="Card.TFrame")
        legend_header.pack(fill="x",pady=(0,8))
        ttk.Label(legend_header,text="Legend",style="CardHeading.TLabel").pack(side="left")
        ttk.Label(legend_header,text="Toggle marker states",style="CardMuted.TLabel").pack(side="right",padx=(12,0))

        legend_items=ttk.Frame(legend,style="Card.TFrame")
        legend_items.pack(fill="x")
        for column in range(4):
            legend_items.columnconfigure(column,weight=1,uniform="map_legend")

        legend_defs=(
            ("reachable","Reachable","#35b979"),
            ("glitched","Glitch-only","#b34bd6"),
            ("out_of_logic","Out of logic","#e05252"),
            ("checked","Checked","#8c9499"),
            ("ignored","Ignored","#d39a45"),
            ("non_progression","Non-progression","#9a8f72"),
            ("unknown","Unknown","#7f91a3"),
        )
        for index,(key,label,color) in enumerate(legend_defs):
            tile=ttk.Frame(legend_items,style="CardAlt.TFrame",padding=(8,6))
            tile.grid(row=index//4,column=index%4,sticky="ew",padx=(0 if index%4==0 else 4,0),pady=(0 if index<4 else 5,0))
            tk.Label(
                tile,text="●",fg=color,bg=palette["card_alt"],
                font="WayFinderLegendDot",borderwidth=0,
            ).pack(side="left",padx=(0,4))
            ttk.Checkbutton(
                tile,text=label,style="CardAlt.TCheckbutton",
                variable=self.map_status_visible[key],command=self._map_option_changed,
            ).pack(side="left",fill="x",expand=True)

        opts=ttk.Frame(controls,style="Card.TFrame",padding=(12,10))
        opts.grid(row=0,column=1,sticky="nsew",padx=(6,0))
        opts_header=ttk.Frame(opts,style="Card.TFrame")
        opts_header.pack(fill="x",pady=(0,8))
        ttk.Label(opts_header,text="Map Controls",style="CardHeading.TLabel").pack(side="left")
        ttk.Label(opts_header,text="View & interaction",style="CardMuted.TLabel").pack(side="right",padx=(12,0))

        option_groups=ttk.Frame(opts,style="Card.TFrame")
        option_groups.pack(fill="both",expand=True)
        for column in range(3):
            option_groups.columnconfigure(column,weight=1,uniform="map_controls")

        display=ttk.Frame(option_groups,style="CardAlt.TFrame",padding=(9,7))
        display.grid(row=0,column=0,sticky="nsew",padx=(0,4))
        ttk.Label(display,text="DISPLAY",style="CardAltTitle.TLabel").pack(anchor="w",pady=(0,3))
        ttk.Checkbutton(display,text="Location labels",style="CardAlt.TCheckbutton",variable=self.map_show_labels,command=self._map_option_changed).pack(anchor="w")
        ttk.Checkbutton(display,text="Tooltips",style="CardAlt.TCheckbutton",variable=self.map_show_tooltips,command=self._map_option_changed).pack(anchor="w")
        ttk.Checkbutton(display,text="Highlight search",style="CardAlt.TCheckbutton",variable=self.map_highlight_search,command=self._map_option_changed).pack(anchor="w")

        navigation=ttk.Frame(option_groups,style="CardAlt.TFrame",padding=(9,7))
        navigation.grid(row=0,column=1,sticky="nsew",padx=4)
        ttk.Label(navigation,text="NAVIGATION",style="CardAltTitle.TLabel").pack(anchor="w",pady=(0,3))
        ttk.Checkbutton(navigation,text="Semantic zoom",style="CardAlt.TCheckbutton",variable=self.map_semantic_zoom,command=self._map_option_changed).pack(anchor="w")
        ttk.Checkbutton(navigation,text="Minimap",style="CardAlt.TCheckbutton",variable=self.map_show_minimap,command=self._minimap_option_changed).pack(anchor="w")

        markers=ttk.Frame(option_groups,style="CardAlt.TFrame",padding=(9,7))
        markers.grid(row=0,column=2,sticky="nsew",padx=(4,0))
        ttk.Label(markers,text="MARKERS",style="CardAltTitle.TLabel").pack(anchor="w",pady=(0,3))
        ttk.Checkbutton(markers,text="Hide completed groups",style="CardAlt.TCheckbutton",variable=self.map_hide_checked_groups,command=self._map_option_changed).pack(anchor="w")
        marker_size_row=ttk.Frame(markers,style="CardAlt.TFrame")
        marker_size_row.pack(fill="x",pady=(4,0))
        ttk.Label(marker_size_row,text="Size",style="CardAltMuted.TLabel").pack(side="left")
        ms=ttk.Combobox(marker_size_row,textvariable=self.map_marker_size,state="readonly",width=8,values=("Small","Medium","Large"))
        ms.pack(side="right",padx=(6,0))
        ms.bind("<<ComboboxSelected>>",lambda _e:self._map_option_changed())

        # Variable(s): `info_row` (info row); named state retained for the surrounding calculation or subsequent calls.
        info_row=ttk.Frame(p); info_row.pack(fill="x",pady=(0,5))
        self.map_hover=tk.StringVar(value="Single-click selects • Double-click opens Path Explorer • Right-click for actions • Middle-drag pans • Home fits map")
        ttk.Label(info_row,textvariable=self.map_hover,style="Muted.TLabel").pack(side="left",fill="x",expand=True)
        self.map_location_counter=tk.StringVar(value="Locations: 0 / 0 visible")
        ttk.Label(info_row,textvariable=self.map_location_counter,style="CardValue.TLabel").pack(side="right",padx=(12,0))
        # Variable(s): `wrap` (wrap); named state retained for the surrounding calculation or subsequent calls.
        wrap=ttk.Frame(p); wrap.pack(fill="both",expand=True)
        self.map_canvas=tk.Canvas(wrap,bg="#170d12",highlightthickness=0)
        # Variable(s): `sx` (sx); named state retained for the surrounding calculation or subsequent calls.
        sx=ttk.Scrollbar(wrap,orient="horizontal",command=self.map_canvas.xview); sy=ttk.Scrollbar(wrap,orient="vertical",command=self.map_canvas.yview)
        sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x"); self.map_canvas.pack(side="left",fill="both",expand=True)
        self.map_canvas.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        self.minimap_canvas=tk.Canvas(self.map_canvas,width=190,height=140,bg="#35202a",highlightthickness=1,highlightbackground="#8a5366",cursor="crosshair"); self.minimap_canvas.place(relx=1.0,rely=0.0,x=-10,y=10,anchor="ne"); self.minimap_canvas.bind("<Button-1>",self._minimap_jump); self.minimap_canvas.bind("<B1-Motion>",self._minimap_jump)
        self.map_canvas.bind("<MouseWheel>", self._map_mousewheel)
        self.map_canvas.bind("<Control-MouseWheel>", self._map_ctrl_mousewheel)
        self.map_canvas.bind("<ButtonPress-2>", self._map_pan_start)
        self.map_canvas.bind("<B2-Motion>", self._map_pan_move)
        self.map_canvas.bind("<ButtonRelease-2>", self._map_pan_end)
        self.map_canvas.bind("<ButtonRelease-1>", self._map_empty_click)
        self.map_canvas.bind("<Escape>", self._map_clear_selection)
        self.root.bind("<Escape>", self._map_clear_selection, add="+")
        self.map_canvas.bind("<Home>", lambda _e:self._map_fit_zoom())
        self.map_canvas.bind("<Enter>", lambda _e:self.map_canvas.focus_set())
        self.map_canvas.configure(cursor="arrow")
        if hasattr(self,"search_var"):
            self.search_var.trace_add("write",lambda *_: self._schedule_map_search_refresh())
        self._scan_map_packs()

    def _schedule_map_search_refresh(self):
        """Coalesce fast typing so search highlighting does not repaint every marker per keystroke."""
        if not self.map_highlight_search.get() or self._closing:
            return
        if self._map_search_after_id is not None:
            try: self.root.after_cancel(self._map_search_after_id)
            except Exception: _ignored("intentional best-effort fallback")
        self._map_search_after_id = self.root.after(90, self._run_map_search_refresh)

    def _run_map_search_refresh(self):
        """Handle run map search refresh."""
        self._map_search_after_id = None
        self._refresh_map_markers()

    def _request_map_render(self, preserve_view=True, delay=90):
        """Debounce/coalesce expensive map renders, keeping only the newest requested view."""
        if self._closing or not hasattr(self, "map_canvas"):
            return
        if getattr(self, "current_page", "") != "Map" and getattr(self, "_map_popout", None) is None:
            self._map_render_deferred = True
            return
        self._map_render_deferred = False
        md = self._current_map_def()
        key = asset_key(self.active_map_pack, md.image, int(self.map_zoom.get())) if md else None
        # Repeated snapshot/marker refreshes must not invalidate useful work or
        # keep postponing the debounce timer for the same image and zoom.
        if key is not None and (self.map_rendering_key == key or
                (self._map_zoom_after_id is not None and getattr(self, '_map_requested_key', None) == key)):
            return
        self._map_requested_key = key
        self._map_failed_key = None  # An explicit request is also a retry.
        # Invalidate any older worker immediately. Its result will never touch Tk.
        self.map_render_generation += 1
        self.map_rendering_key = None
        if self._map_zoom_after_id is not None:
            try: self.root.after_cancel(self._map_zoom_after_id)
            except Exception: _ignored("intentional best-effort fallback")
        # Variable(s): `md` (metadata); named state retained for the surrounding calculation or subsequent calls.
        md = self._current_map_def()
        if md:
            self.map_status.set(f"{md.title} • {int(self.map_zoom.get())}% • preparing map in background…")
        if hasattr(self,"map_render_progress"):
            try: self.map_render_progress.start(12)
            except tk.TclError: _ignored("intentional best-effort fallback")
        if self._map_popout_render_progress is not None:
            try: self._map_popout_render_progress.start(12)
            except tk.TclError: _ignored("intentional best-effort fallback")
        self._map_zoom_after_id = self.root.after(max(0, int(delay)), lambda:self._run_requested_map_render(preserve_view))

    def _run_requested_map_render(self, preserve_view):
        """Handle run requested map render."""
        self._map_zoom_after_id = None
        self._render_map(preserve_view=preserve_view)

    def _map_reset_zoom(self):
        """Handle map reset zoom."""
        if int(self.map_zoom.get()) != 100:
            self.map_zoom.set(100)
            self._request_map_render(preserve_view=True, delay=40)

    def _map_fit_zoom(self):
        """Choose the largest supported zoom that fits the whole current map in the viewport."""
        if self.map_photo is None or not hasattr(self, "map_canvas"):
            return
        # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
        current=max(1, int(self.map_zoom.get())) / 100.0
        # Variable(s): `base_w` (base w); named state retained for the surrounding calculation or subsequent calls.
        base_w=max(1, self.map_photo.width() / current); base_h=max(1, self.map_photo.height() / current)
        # Variable(s): `view_w` (view w); named state retained for the surrounding calculation or subsequent calls.
        view_w=max(1, self.map_canvas.winfo_width()-4); view_h=max(1, self.map_canvas.winfo_height()-4)
        # Variable(s): `target` (target); named state retained for the surrounding calculation or subsequent calls.
        target=100.0*min(view_w/base_w, view_h/base_h)
        # Variable(s): `levels` (levels); named state retained for the surrounding calculation or subsequent calls.
        levels=ZOOM_CACHE_LEVELS
        # Variable(s): `chosen` (chosen); named state retained for the surrounding calculation or subsequent calls.
        chosen=max((z for z in levels if z <= target), default=min(levels))
        if chosen != int(self.map_zoom.get()):
            self.map_zoom.set(chosen)
            self._request_map_render(preserve_view=False, delay=40)
        else:
            self.map_canvas.xview_moveto(0); self.map_canvas.yview_moveto(0)

    def _rescan_map_packs(self):
        """Rescan from disk and invalidate both decoded and scaled image caches."""
        self.map_photo_cache.clear(); self.map_background_key=None; self.map_photo=None; self._minimap_key=None; self._minimap_photo=None
        with self._map_source_cache_lock:
            self.map_source_cache.clear()
        with self._map_scaled_cache_lock:
            self.map_scaled_cache.clear()
        self._scan_map_packs()

    def _map_option_changed(self):
        """Apply legend/map-option changes immediately without reloading the map image."""
        self._remember_game_filters()
        # A legend/filter toggle can change visibility without changing any
        # location state. Force persistent Canvas markers to be re-evaluated.
        self._refresh_map_markers(force_rebuild=True)
        self._refresh_map_group_popup()
        self._draw_route_overlay()
        self._refresh_popout_map()

    def _schedule_hint_pulse(self):
        """Handle schedule hint pulse."""
        if self._closing or not hasattr(self,"map_canvas"): return
        if self._map_hint_after_id is not None: return
        if not any(getattr(x,"hinted",False) and getattr(x,"status","") != "checked" for x in self.snapshot.locations): return
        # /**
        #  * Function: tick
        #  * Purpose: Perform the tick operation while keeping the surrounding subsystem state consistent.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def tick():
            """Handle tick."""
            self._map_hint_after_id=None
            if self._closing: return
            self._map_hint_phase=not self._map_hint_phase
            self._refresh_map_markers(force_rebuild=True)
            self._schedule_hint_pulse()
        self._map_hint_after_id=self.root.after(850,tick)

    def _current_map_status_counts(self):
        """Handle current map status counts."""
        status_order=("reachable","glitched","out_of_logic","checked","ignored","non_progression","unknown")
        counts={status:0 for status in status_order}
        pack=self.active_map_pack
        md=self._current_map_def() if pack else None
        if not pack or md is None:
            return counts,0

        # Resolve against the current seed and count each AP check exactly once.
        # A location can occur in more than one visual marker in unusual packs;
        # ``seen_locations`` prevents that from inflating the area total.
        state={location.name:location for location in (self.snapshot.locations or [])}
        seen_locations=set()
        for marker in pack.markers_by_map.get(md.name,()):
            for member_index,member_name in enumerate(marker.member_names):
                location=self._map_marker_member_location(marker,member_index,state)
                if location is None:
                    continue
                resolved_name=str(getattr(location,"name","") or member_name)
                identity=(getattr(location,"id",None),resolved_name)
                if identity in seen_locations:
                    continue
                seen_locations.add(identity)
                status=self._map_effective_location_status(location)
                if status not in counts:
                    status="unknown"
                counts[status]+=1
        return counts,sum(counts.values())

    def _draw_current_area_progress(self):
        """Handle draw current area progress."""
        canvas=getattr(self,"map_area_progress_canvas",None)
        if canvas is None:
            return
        canvas.delete("all")
        width=max(1,int(canvas.winfo_width()))
        height=max(1,int(canvas.winfo_height()))
        counts,total=self._current_map_status_counts()
        if total <= 0:
            canvas.create_rectangle(0,0,width,height,fill=self._palette()["card"],outline="")
            canvas.create_text(width/2,height/2,text="No generated checks on this map",fill=self._palette()["muted"],font="WayFinderSmall")
            return

        colors={
            "reachable":"#35b979",
            "glitched":"#b34bd6",
            "out_of_logic":"#e05252",
            "checked":"#8c9499",
            "ignored":"#d39a45",
            "non_progression":"#9a8f72",
            "unknown":"#7f91a3",
        }
        x=0.0
        order=("reachable","glitched","out_of_logic","checked","ignored","non_progression","unknown")
        for index,status in enumerate(order):
            count=counts[status]
            if not count:
                continue
            next_x=width if index == len(order)-1 else x+(width*count/total)
            # Guarantee the final *visible* segment closes the bar exactly.
            later=sum(counts[name] for name in order[index+1:])
            if later == 0:
                next_x=width
            canvas.create_rectangle(x,0,next_x,height,fill=colors[status],outline="")
            x=next_x

    def _refresh_current_area_progress(self):
        """Handle refresh current area progress."""
        if not hasattr(self,"map_current_area"):
            return
        # Current area is live player state, not the map the user is browsing.
        # map_selector_var is presentation/navigation state and must never be used
        # as a proxy for the player's actual area.
        title=str(getattr(self, "map_last_runtime_target", "") or "").strip()
        if not title:
            key=str(getattr(self.snapshot,"map_page_setting_key","") or "").strip()
            raw=getattr(self.snapshot,"raw_map_page_datastorage_value",None)
            if key and raw is not None and not isinstance(raw,(dict,list,tuple,set)):
                title=str(raw).strip()
        room=str(getattr(self.snapshot,"player_position_label","") or "").strip()
        self.map_current_area.set(f"Current area: {title or '—'}" + (f" • Room: {room}" if room else ""))

        counts,total=self._current_map_status_counts()
        labels=(("reachable","Reachable"),("glitched","Glitch-only"),("out_of_logic","Out of logic"),("checked","Checked"),("ignored","Ignored"),("unknown","Unknown"))
        detail=[f"{label}: {counts[key]}" for key,label in labels if counts[key]]
        if hasattr(self,"map_area_progress_detail"):
            self.map_area_progress_detail.set((f"{total} check{'s' if total != 1 else ''} • " + " • ".join(detail)) if total else "No generated checks on selected map")
        if hasattr(self,"map_area_progress_scale"):
            checked_percent=(100.0*counts["checked"]/total) if total else 0.0
            self.map_area_progress_scale.set(f"0%    •    Checked {checked_percent:.0f}%" + " "*8 + "100%")
        self._draw_current_area_progress()

    def _refresh_map_from_snapshot(self):
        """Re-match packs, follow *changed* runtime map signals, and repaint marker deltas.

        Network traffic such as chat, hints and received items also produces fresh
        snapshots.  A snapshot by itself must not be treated as a request to jump
        back to the player's current map: doing that makes it impossible to browse
        another map while connected.  We therefore remember the last runtime map
        target and only auto-follow when that target itself changes.
        """
        if not hasattr(self,"map_canvas"):
            print("[MAP-DEBUG] refresh_map_from_snapshot ABORT: map_canvas does not exist", flush=True)
            return
        map_visible = getattr(self,"current_page", "") == "Map" or getattr(self,"_map_popout",None) is not None
        live={x.name for x in self.snapshot.locations}
        print(f"[MAP-DEBUG] refresh_map_from_snapshot ENTER seq={getattr(self.snapshot,'snapshot_sequence',0)} visible={map_visible} page={getattr(self,'current_page','')!r} game={self.snapshot.game!r} live={len(live)} active_pack={getattr(getattr(self,'active_map_pack',None),'display_name',None)!r} selected_map={self.map_selector_var.get()!r}", flush=True)

        # A hidden Map page is still a live view once its pack/canvas has been
        # initialised.  Older code returned here, so accepted snapshots updated
        # Checks but marker canvas state stayed stale until the Map tab's activation
        # callback forced a repaint.  Keep expensive background/image rendering
        # deferred, but apply the cheap in-place marker state delta immediately.
        if not map_visible:
            self._map_render_deferred=True
            pack,matches=self._preferred_map_pack(live,self.snapshot.game)
            if self.snapshot.game and self.snapshot.connected and pack is None and self.active_map_pack is None:
                activation_key=(str(self.snapshot.game), getattr(self.snapshot, "slot", ""))
                if getattr(self, "_map_connection_activation_key", None) != activation_key:
                    self._map_connection_activation_key=activation_key
                    print(f"[MAP-DEBUG] hidden connection activation: no active pack for game={self.snapshot.game!r}; rescanning installed packs", flush=True)
                    if hasattr(self, "events"):
                        self.events.put(("log", f"[MAP-AUTO] Connected game {self.snapshot.game!r}; activating compatible installed map pack."))
                    self._scan_map_packs()
            print(f"[MAP-DEBUG] hidden pack match pack={getattr(pack,'display_name',None)!r} matches={matches} pack_changed={pack is not self.active_map_pack or self.snapshot.game != self.map_last_game}", flush=True)

            # Pack matching and map selection are state work, not rendering work.
            # Do them even while the Map page is hidden so a newly connected seed
            # auto-selects its map without requiring the user to click Map first.
            pack_changed = pack is not self.active_map_pack or self.snapshot.game != self.map_last_game
            if pack_changed:
                self.active_map_pack=pack; self.map_last_game=self.snapshot.game
                self.map_last_runtime_target=None
                self._restore_game_filters()
                if pack and pack.has_python:
                    pack.load_python()
                    if pack.python_error:
                        self._append_log(f"Map-pack Python for {pack.display_name}: {pack.python_error}")
                if pack:
                    names=self._ut_ordered_map_titles(pack,self.snapshot)
                    self.map_selector.configure(values=names)
                    runtime_target=self._runtime_map_target(pack,names,self.snapshot)
                    self.map_last_runtime_target=runtime_target
                    chosen=runtime_target or self._choose_map_for_pack(pack,names,self.snapshot,prefer_hook=True)
                    print(f"[MAP-DEBUG] hidden auto-select names={names!r} runtime_target={runtime_target!r} chosen={chosen!r}", flush=True)
                    if chosen:
                        self.map_selector_var.set(chosen)
                else:
                    self.map_selector.configure(values=()); self.map_selector_var.set("")
            elif pack:
                # Continue following genuine runtime map transitions while hidden.
                names=self._ut_ordered_map_titles(pack,self.snapshot)
                runtime_target=self._runtime_map_target(pack,names,self.snapshot)
                previous_target=self.map_last_runtime_target
                self.map_last_runtime_target=runtime_target
                # Auto-follow only when the *player* changes area.  A manual map
                # selection is browsing state and must remain independent until the
                # runtime reports a genuine area transition.
                if runtime_target and runtime_target != previous_target:
                    if runtime_target != self.map_selector_var.get():
                        self.map_selector_var.set(runtime_target)
                        self._remember_current_map()

            if pack is self.active_map_pack and self.snapshot.game == self.map_last_game and pack is not None:
                self._map_marker_refresh_deferred=False
                try:
                    print(f"[MAP-DEBUG] hidden marker refresh CALL selected={self.map_selector_var.get()!r} background_key={getattr(self,'map_background_key',None)!r} photo={'yes' if getattr(self,'map_photo',None) is not None else 'no'}", flush=True)
                    self._refresh_map_markers(force_rebuild=False)
                    self._refresh_current_area_progress()
                    if hasattr(self, "events"):
                        self.events.put(("log", f"[MAP-REFRESH] Applied hidden-page marker delta from live snapshot; locations={len(live)} matched={matches}"))
                except (AttributeError, KeyError, tk.TclError) as exc:
                    self._map_marker_refresh_deferred=True
                    if hasattr(self, "events"):
                        self.events.put(("log", f"[MAP-REFRESH] Hidden-page marker delta deferred: {type(exc).__name__}: {exc}"))
                return
            self._map_marker_refresh_deferred=True
            return

        self._map_marker_refresh_deferred=False
        pack,matches=self._preferred_map_pack(live,self.snapshot.game)

        # Connection-time activation: the first live snapshot can arrive before the
        # asynchronous installed-map scan has populated ``self.map_packs``.  In
        # that race the dashboard can already report a compatible pack from its
        # own readiness probe while the Map page still has active_pack=None.
        # Kick a fresh discovery as soon as the connected game is known; the scan
        # completion callback selects the matching pack and its initial/current map
        # on the Tk thread without requiring a Map-page click.
        if self.snapshot.game and self.snapshot.connected and pack is None and self.active_map_pack is None:
            activation_key=(str(self.snapshot.game), getattr(self.snapshot, "slot", ""))
            if getattr(self, "_map_connection_activation_key", None) != activation_key:
                self._map_connection_activation_key=activation_key
                print(f"[MAP-DEBUG] connection activation: no active pack for game={self.snapshot.game!r}; rescanning installed packs", flush=True)
                if hasattr(self, "events"):
                    self.events.put(("log", f"[MAP-AUTO] Connected game {self.snapshot.game!r}; activating compatible installed map pack."))
                self._scan_map_packs()

        pack_changed = pack is not self.active_map_pack or self.snapshot.game != self.map_last_game
        if pack_changed:
            self.active_map_pack=pack; self.map_last_game=self.snapshot.game
            self.map_last_runtime_target=None
            self._restore_game_filters()
            if pack and pack.has_python:
                pack.load_python()
                if pack.python_error:
                    self._append_log(f"Map-pack Python for {pack.display_name}: {pack.python_error}")
            if pack:
                names=self._ut_ordered_map_titles(pack,self.snapshot); self.map_selector.configure(values=names)
                # Resolve and remember the live target once when a pack/game is first
                # attached.  Subsequent snapshots only follow a changed target.
                runtime_target=self._runtime_map_target(pack,names,self.snapshot)
                self.map_last_runtime_target=runtime_target
                chosen=runtime_target or self._choose_map_for_pack(pack,names,self.snapshot,prefer_hook=True)
                if chosen: self.map_selector_var.set(chosen)
                self._render_map(preserve_view=False)
            else:
                self.map_selector.configure(values=()); self.map_selector_var.set("")
        elif pack:
            names=self._ut_ordered_map_titles(pack,self.snapshot)
            runtime_target=self._runtime_map_target(pack,names,self.snapshot)
            previous_target=self.map_last_runtime_target
            self.map_last_runtime_target=runtime_target
            # Auto-follow only on a genuine live player-area transition.  This lets
            # the user browse another map without rewriting or being mistaken for
            # the player's current area.
            if runtime_target and runtime_target != previous_target:
                if runtime_target != self.map_selector_var.get():
                    self.map_selector_var.set(runtime_target)
                    self._remember_current_map()
                    self._request_map_render(preserve_view=False,delay=40)
        if pack:
            api=(f" • Pack API v{pack.python_api_version}" if pack.has_python and pack.python_api_compatible and pack.python_api_version is not None else (" • Native tracker Python" if pack.has_python and pack.python_api_compatible else (" • Python hooks disabled" if pack.has_python else "")))
            variant_text=(f"  •  Variant: {pack.variants.get(pack.variant_uid, pack.variant_uid)}" if getattr(pack,"variants",None) else "")
            self.map_status.set(f"{pack.display_name}{variant_text}  •  {matches} live locations matched  •  {len(pack.maps)} maps  •  {len(pack.markers)} markers{api}")
            self._refresh_map_markers()
        else:
            self.map_canvas.delete("all")
            self._map_marker_items.clear(); self._map_marker_visual_state.clear(); self._map_marker_layout_key=None
            detail=f"{len(self.map_packs)} pack(s) installed, but none match this game's live locations." if self.map_packs else "No map packs are installed yet."
            self.map_status.set(detail+f"  Library: {default_pack_dir()}")
            if hasattr(self,"map_location_counter"): self.map_location_counter.set("Locations: 0 / 0 visible")

        self._refresh_current_area_progress()
        self._refresh_dashboard_overview()

    def _installed_map_pack_labels(self):
        """Handle installed map pack labels."""
        return [f"{pack.display_name}  [{pack.source.name}]" for pack in self.map_packs]

    def _refresh_installed_maps_page(self):
        """Handle refresh installed maps page."""
        if not hasattr(self,"installed_maps_tree"):
            return
        self.installed_maps_tree.delete(*self.installed_maps_tree.get_children())
        active=self.active_map_pack
        for index,pack in enumerate(self.map_packs):
            linked_games=[g for g,src in (getattr(self,"game_map_pack_links",{}) or {}).items() if str(src).casefold()==str(pack.source).casefold()]
            state="Active" if pack is active else "Installed"
            if linked_games: state += " • Linked"
            game=getattr(pack,"game","") or getattr(pack,"display_name","")
            maps=len(getattr(pack,"maps",[]) or [])
            markers=len(getattr(pack,"markers",[]) or [])
            self.installed_maps_tree.insert("", "end", iid=str(index), values=(pack.display_name,game,maps,markers,state,str(pack.source)))
        labels=["Auto"]+self._installed_map_pack_labels()
        self.installed_map_selector.configure(values=labels)
        current=self.active_map_pack_choice.get()
        if current not in labels:
            self.active_map_pack_choice.set("Auto")
        game=str(getattr(self.snapshot,"game","") or "").strip()
        linked=self._linked_map_pack_for_game(game) if game else None
        link_text=f" • {game} → {linked.display_name}" if game and linked else (f" • {game}: not linked" if game else "")
        self.installed_maps_summary.set(f"{len(self.map_packs)} installed map pack{'s' if len(self.map_packs)!=1 else ''} • Active mode: {self.active_map_pack_choice.get()}{link_text}")

    def _installed_map_choice_changed(self, _event=None):
        """Handle installed map choice changed."""
        self.settings["active_map_pack_choice"]=self.active_map_pack_choice.get()
        self._save_settings()
        self.map_last_game=""
        self.map_last_runtime_target=None
        self._scan_map_packs()
        self._refresh_installed_maps_page()

    def _installed_map_tree_selected(self, _event=None):
        """Handle installed map tree selected."""
        selection=self.installed_maps_tree.selection()
        if not selection:
            return
        try:
            pack=self.map_packs[int(selection[0])]
        except (ValueError,IndexError):
            return
        label=f"{pack.display_name}  [{pack.source.name}]"
        self.active_map_pack_choice.set(label)
        self._installed_map_choice_changed()

    def _linked_map_pack_for_game(self, game):
        """Return the installed pack explicitly linked to an Archipelago game."""
        key=str(game or "").strip().casefold()
        source=str((getattr(self,"game_map_pack_links",{}) or {}).get(key,"") or "")
        if not source: return None
        return next((p for p in self.map_packs if str(p.source).casefold()==source.casefold()),None)

    def _link_selected_map_pack_to_game(self):
        """Persist the selected installed pack as the default pack for the connected game."""
        game=str(getattr(self.snapshot,"game","") or "").strip()
        if not game:
            self.map_status.set("Connect to an Archipelago game before linking a map pack.")
            return
        selection=self.installed_maps_tree.selection() if hasattr(self,"installed_maps_tree") else ()
        try: pack=self.map_packs[int(selection[0])] if selection else self.active_map_pack
        except (ValueError,IndexError): pack=None
        if not pack:
            self.map_status.set("Select an installed map pack to link to the current game.")
            return
        self.game_map_pack_links[game.casefold()]=str(pack.source)
        self.settings["game_map_pack_links"]=dict(self.game_map_pack_links)
        self._save_settings()
        self.map_last_game=""; self.map_last_runtime_target=None
        self._append_log(f"Linked game {game!r} to map pack {pack.display_name!r}.")
        self._scan_map_packs(); self._refresh_installed_maps_page()

    def _unlink_current_game_map_pack(self):
        """Remove the persistent map-pack association for the connected game."""
        game=str(getattr(self.snapshot,"game","") or "").strip()
        if not game:
            self.map_status.set("No connected game to unlink.")
            return
        removed=self.game_map_pack_links.pop(game.casefold(),None)
        self.settings["game_map_pack_links"]=dict(self.game_map_pack_links)
        self._save_settings()
        self.map_last_game=""; self.map_last_runtime_target=None
        if removed: self._append_log(f"Removed map-pack link for game {game!r}.")
        self._scan_map_packs(); self._refresh_installed_maps_page()

    def _build_installed_maps(self):
        """Build the dedicated installed-map-pack management page."""
        p=self._page("Installed Maps")
        h=ttk.Frame(p); h.pack(fill="x",pady=(4,10))
        ttk.Label(h,text="Installed Maps",style="Title.TLabel").pack(side="left")

        controls=ttk.Frame(p,style="Card.TFrame",padding=(14,12))
        controls.pack(fill="x",pady=(0,10))
        ttk.Label(controls,text="ACTIVE MAP",style="CardTitle.TLabel").grid(row=0,column=0,sticky="w")
        ttk.Label(controls,text="Auto chooses a matching pack. You can also link a pack to the connected game so that exact pack is activated whenever that game connects.",style="CardMuted.TLabel",wraplength=900,justify="left").grid(row=1,column=0,columnspan=5,sticky="w",pady=(3,8))
        self.installed_map_selector=ttk.Combobox(controls,textvariable=self.active_map_pack_choice,state="readonly",width=48,style="MapName.TCombobox")
        self.installed_map_selector.grid(row=2,column=0,sticky="w")
        self.installed_map_selector.bind("<<ComboboxSelected>>",self._installed_map_choice_changed)
        ttk.Button(controls,text="Install Map Pack…",style="Accent.TButton",command=self._install_map_pack).grid(row=2,column=1,padx=(10,0))
        ttk.Button(controls,text="Rescan",style="Accent.TButton",command=self._rescan_map_packs).grid(row=2,column=2,padx=(6,0))
        ttk.Button(controls,text="Open Pack Folder",style="Accent.TButton",command=self._open_map_pack_folder).grid(row=2,column=3,padx=(6,0))
        self.map_install_button=controls.grid_slaves(row=2,column=1)[0]

        table_card=ttk.Frame(p,style="Card.TFrame",padding=(14,12))
        table_card.pack(fill="both",expand=True)
        ttk.Label(table_card,text="INSTALLED MAP PACKS",style="CardTitle.TLabel").pack(anchor="w")
        self.installed_maps_summary=tk.StringVar(value="No map packs scanned yet")
        ttk.Label(table_card,textvariable=self.installed_maps_summary,style="CardMuted.TLabel").pack(anchor="w",pady=(3,8))
        cols=("Name","Game / Pack","Maps","Markers","Status","Folder")
        self.installed_maps_tree=ttk.Treeview(table_card,columns=cols,show="headings",selectmode="browse",style="Emphasis.Treeview")
        widths=(220,220,65,70,85,360)
        for col,width in zip(cols,widths):
            self.installed_maps_tree.heading(col,text=col)
            self.installed_maps_tree.column(col,width=width,anchor="w",stretch=(col in ("Name","Game / Pack","Folder")))
        self.installed_maps_tree.pack(fill="both",expand=True)
        self.installed_maps_tree.bind("<Double-1>",self._installed_map_tree_selected)

        actions=ttk.Frame(p); actions.pack(fill="x",pady=(8,0))
        ttk.Button(actions,text="Use Selected",style="Accent.TButton",command=self._installed_map_tree_selected).pack(side="left")
        ttk.Button(actions,text="Link Selected to Current Game",style="Accent.TButton",command=self._link_selected_map_pack_to_game).pack(side="left",padx=(6,0))
        ttk.Button(actions,text="Unlink Current Game",style="Accent.TButton",command=self._unlink_current_game_map_pack).pack(side="left",padx=(6,0))
        ttk.Button(actions,text="Revalidate Active",style="Accent.TButton",command=self._revalidate_active_map_pack).pack(side="left",padx=(6,0))
        ttk.Button(actions,text="Remove Active",style="Accent.TButton",command=self._remove_map_pack).pack(side="left",padx=(6,0))

        self._refresh_installed_maps_page()

    def _current_map_def(self):
        """Handle current map def."""
        if not self.active_map_pack:return None
        return self.active_map_pack.maps_by_title.get(self.map_selector_var.get())

