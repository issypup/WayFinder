"""Provide map popout support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

from .map_shared import *

class MapPopoutMixin:
    """Map subsystem responsibilities extracted from MapPageMixin."""
    def _popout_map(self):
        """Open a fully live, non-blocking second map window using the same tracker state."""
        if not hasattr(self,"map_canvas") or not self.active_map_pack:
            return
        if self._map_popout is not None:
            try:
                if self._map_popout.winfo_exists():
                    self._map_popout.deiconify(); self._map_popout.lift(); self._map_popout.focus_force(); return
            except tk.TclError:
                _ignored("intentional best-effort fallback")
        top=tk.Toplevel(self.root); self._map_popout=top
        if getattr(self,"_map_render_deferred",False):
            self._request_map_render(preserve_view=True,delay=0)
        top.title(f"WayFinder Map — {self.map_selector_var.get()}"); top.geometry("1100x800"); top.minsize(620,420)
        top.protocol("WM_DELETE_WINDOW", self._close_popout_map)

        outer=ttk.Frame(top,padding=10); outer.pack(fill="both",expand=True)
        header=ttk.Frame(outer); header.pack(fill="x",pady=(0,6))
        ttk.Label(header,text="Map",style="Title.TLabel").pack(side="left")
        ttk.Button(header,text="←",width=3,command=self._map_history_back).pack(side="left",padx=(10,2))
        ttk.Button(header,text="→",width=3,command=self._map_history_forward).pack(side="left",padx=2)
        ttk.Button(header,text="+",width=3,command=lambda:self._change_map_zoom(1)).pack(side="right")
        zoom_box=ttk.Combobox(header,textvariable=self.map_zoom,state="readonly",width=7,values=ZOOM_CACHE_LEVELS); zoom_box.pack(side="right",padx=4)
        zoom_box.bind("<<ComboboxSelected>>",lambda _e:self._request_map_render(preserve_view=True))
        ttk.Button(header,text="−",width=3,command=lambda:self._change_map_zoom(-1)).pack(side="right")
        ttk.Button(header,text="100%",width=5,command=self._map_reset_zoom).pack(side="right",padx=(6,0))
        ttk.Button(header,text="Fit",width=4,command=self._map_fit_zoom).pack(side="right",padx=(4,0))
        ttk.Label(header,text="Zoom",style="Muted.TLabel").pack(side="right",padx=(6,2))
        selector=ttk.Combobox(header,textvariable=self.map_selector_var,state="readonly",width=24,style="MapName.TCombobox",values=self.map_selector.cget("values")); selector.pack(side="right",padx=6)
        selector.bind("<<ComboboxSelected>>",self._map_selected_by_user)

        ttk.Label(outer,textvariable=self.map_current_area,style="CardValue.TLabel").pack(anchor="w",pady=(0,3))
        palette=self._palette()
        progress=tk.Canvas(outer,height=24,highlightthickness=1,highlightbackground=palette.get("border",palette["accent_soft"]),bg=palette["card"])
        progress.pack(fill="x",pady=(0,2)); self._map_popout_progress_canvas=progress
        ttk.Label(outer,textvariable=self.map_area_progress_scale,style="Muted.TLabel").pack(fill="x")
        self._map_popout_progress_detail=tk.StringVar(value=self.map_area_progress_detail.get())
        ttk.Label(outer,textvariable=self._map_popout_progress_detail,style="Muted.TLabel",wraplength=1000,justify="left").pack(anchor="w",pady=(0,4))
        self._map_popout_status=tk.StringVar(value=self.map_status.get())
        ttk.Label(outer,textvariable=self._map_popout_status,style="Muted.TLabel",wraplength=1000,justify="left").pack(anchor="w",pady=(0,2))
        self._map_popout_render_progress=ttk.Progressbar(outer,mode="indeterminate"); self._map_popout_render_progress.pack(fill="x",pady=(0,5))

        controls=ttk.Frame(outer); controls.pack(fill="x",pady=(0,7))
        legend=ttk.Frame(controls,style="Card.TFrame",padding=(10,8)); legend.pack(side="left",fill="x",expand=True)
        ttk.Label(legend,text="LEGEND  •  click to hide / show",style="CardTitle.TLabel").pack(anchor="w",pady=(0,5))
        legend_items=ttk.Frame(legend,style="Card.TFrame"); legend_items.pack(fill="x")
        for key,label,color in (("reachable","Reachable","#35b979"),("glitched","Glitch-only","#b34bd6"),("out_of_logic","Out of logic","#e05252"),("checked","Checked","#8c9499"),("ignored","Ignored","#d39a45"),("unknown","Unknown / Untracked","#7f91a3")):
            row=ttk.Frame(legend_items,style="Card.TFrame"); row.pack(side="left",padx=(0,10))
            tk.Label(row,text="●",fg=color,bg=palette["card"],font="WayFinderLegendDot").pack(side="left",padx=(0,2))
            ttk.Checkbutton(row,text=label,style="Card.TCheckbutton",variable=self.map_status_visible[key],command=self._map_option_changed).pack(side="left")
        opts=ttk.Frame(controls,style="Card.TFrame",padding=(10,8)); opts.pack(side="right",padx=(8,0))
        ttk.Label(opts,text="MAP OPTIONS",style="CardTitle.TLabel").grid(row=0,column=0,columnspan=3,sticky="w",pady=(0,5))
        ttk.Checkbutton(opts,text="Location labels",style="Card.TCheckbutton",variable=self.map_show_labels,command=self._map_option_changed).grid(row=1,column=0,sticky="w",padx=(0,8))
        ttk.Checkbutton(opts,text="Tooltips",style="Card.TCheckbutton",variable=self.map_show_tooltips,command=self._map_option_changed).grid(row=1,column=1,sticky="w",padx=(0,8))
        ttk.Checkbutton(opts,text="Hide completed groups",style="Card.TCheckbutton",variable=self.map_hide_checked_groups,command=self._map_option_changed).grid(row=1,column=2,sticky="w")
        ttk.Checkbutton(opts,text="Highlight search",style="Card.TCheckbutton",variable=self.map_highlight_search,command=self._map_option_changed).grid(row=2,column=0,sticky="w",pady=(3,0))
        ttk.Checkbutton(opts,text="Minimap",style="Card.TCheckbutton",variable=self.map_show_minimap,command=self._minimap_option_changed).grid(row=3,column=0,sticky="w",pady=(3,0))
        ttk.Checkbutton(opts,text="Semantic zoom",style="Card.TCheckbutton",variable=self.map_semantic_zoom,command=self._map_option_changed).grid(row=3,column=2,sticky="w",pady=(3,0))
        ttk.Label(opts,text="Marker size",style="CardMuted.TLabel").grid(row=2,column=1,sticky="e",pady=(3,0))
        ms=ttk.Combobox(opts,textvariable=self.map_marker_size,state="readonly",width=8,values=("Small","Medium","Large")); ms.grid(row=2,column=2,sticky="w",pady=(3,0)); ms.bind("<<ComboboxSelected>>",lambda _e:self._map_option_changed())

        info=ttk.Frame(outer); info.pack(fill="x",pady=(0,5))
        ttk.Label(info,textvariable=self.map_hover,style="Muted.TLabel").pack(side="left",fill="x",expand=True)
        self._map_popout_location_counter=tk.StringVar(value=self.map_location_counter.get())
        ttk.Label(info,textvariable=self._map_popout_location_counter,style="CardValue.TLabel").pack(side="right",padx=(12,0))

        wrap=ttk.Frame(outer); wrap.pack(fill="both",expand=True)
        canvas=tk.Canvas(wrap,bg="#170d12",highlightthickness=0); self._map_popout_canvas=canvas
        sx=ttk.Scrollbar(wrap,orient="horizontal",command=canvas.xview); sy=ttk.Scrollbar(wrap,orient="vertical",command=canvas.yview)
        sy.pack(side="right",fill="y"); sx.pack(side="bottom",fill="x"); canvas.pack(side="left",fill="both",expand=True)
        canvas.configure(xscrollcommand=sx.set,yscrollcommand=sy.set)
        canvas.bind("<MouseWheel>",self._map_popout_mousewheel); canvas.bind("<Control-MouseWheel>",self._map_popout_mousewheel)
        canvas.bind("<ButtonPress-2>",lambda e:setattr(self,"_map_popout_drag_start",(e.x,e.y,canvas.xview()[0],canvas.yview()[0])))
        canvas.bind("<B2-Motion>",self._map_popout_pan_move)
        progress.bind("<Configure>",lambda _e:self._draw_popout_area_progress())
        self._refresh_popout_map()

    def _close_popout_map(self):
        """Handle close popout map."""
        top=self._map_popout; self._map_popout=None; self._map_popout_canvas=None; self._map_popout_photo=None
        self._map_popout_status=None; self._map_popout_location_counter=None; self._map_popout_progress_canvas=None; self._map_popout_progress_detail=None; self._map_popout_render_progress=None
        if top is not None:
            try: top.destroy()
            except tk.TclError: _ignored("intentional best-effort fallback")

    def _map_popout_mousewheel(self,event):
        """Handle map popout mousewheel."""
        self._change_map_zoom(1 if event.delta>0 else -1,event=None); return "break"

    def _map_popout_pan_move(self,event):
        """Handle map popout pan move."""
        canvas=self._map_popout_canvas; start=getattr(self,"_map_popout_drag_start",None)
        if canvas is None or not start:return
        x0,y0,xv,yv=start; sw=max(1,canvas.bbox("all")[2] if canvas.bbox("all") else 1); sh=max(1,canvas.bbox("all")[3] if canvas.bbox("all") else 1)
        canvas.xview_moveto(max(0,min(1,xv-(event.x-x0)/sw))); canvas.yview_moveto(max(0,min(1,yv-(event.y-y0)/sh)))

    def _draw_popout_area_progress(self):
        """Handle draw popout area progress."""
        canvas=self._map_popout_progress_canvas
        if canvas is None:return
        # Mirror the already-computed main progress canvas rather than recomputing tracker logic.
        canvas.delete("all")
        try:
            w=max(1,canvas.winfo_width()); h=max(1,canvas.winfo_height())
            main=self.map_area_progress_canvas; items=main.find_all(); srcw=max(1,main.winfo_width())
            for item in items:
                coords=main.coords(item); fill=main.itemcget(item,"fill"); outline=main.itemcget(item,"outline")
                if len(coords)==4:
                    x1,y1,x2,y2=coords; scale=w/srcw; canvas.create_rectangle(x1*scale,y1,x2*scale,y2,fill=fill,outline=outline)
        except tk.TclError: _ignored("intentional best-effort fallback")

    def _refresh_popout_map(self):
        """Handle refresh popout map."""
        canvas=self._map_popout_canvas
        if canvas is None:
            return
        try:
            if not canvas.winfo_exists():return
        except tk.TclError:return
        photo=self.map_photo; pack=self.active_map_pack; md=self._current_map_def()
        canvas.delete("all")
        if photo is None or pack is None or md is None:
            canvas.create_text(24,24,text="Map is still loading…",anchor="nw",fill="white"); return
        self._map_popout_photo=photo
        draw_map_photo(canvas,photo); canvas.configure(scrollregion=(0,0,photo.width(),photo.height()))
        factor=int(self.map_zoom.get())/100.0; state={x.name:x for x in self.snapshot.locations}; shown=0; total=0
        status_palette={"reachable":"#35b979","glitched":"#b34bd6","out_of_logic":"#e05252","checked":"#8c9499","ignored":"#d39a45","non_progression":"#9a8f72","unknown":"#7f91a3"}
        ui_palette=self._palette()
        r={"Small":5.5,"Medium":8.0,"Large":11.0}.get(self.map_marker_size.get(),8.0)
        popout_markers=pack.markers_by_map.get(md.name,())
        popout_positions=self._map_marker_display_positions(popout_markers,factor,r)
        for marker_index,marker in enumerate(popout_markers):
            statuses=[]; names=[]
            if getattr(marker,"is_entrance_marker",False):
                status=self._map_entrance_marker_status(marker)
                statuses.append(status if status in self.map_status_visible else "unknown")
                names.append(marker.location_name); total+=1
                if self.map_status_visible.get(status,self.map_status_visible["unknown"]).get(): shown+=1
            elif getattr(marker,"is_exit_marker",False):
                statuses.append("unknown"); names.append(marker.location_name); total+=1
                if self.map_status_visible["unknown"].get(): shown+=1
            for member_index,name in enumerate(() if getattr(marker,"is_synthetic_marker",False) else marker.member_names):
                loc=self._map_marker_member_location(marker,member_index,state)
                if loc is None:continue
                total+=1; status=self._map_effective_location_status(loc)
                if status not in self.map_status_visible:status="unknown"
                if self.map_status_visible[status].get(): statuses.append(status); names.append(name); shown+=1
            if not statuses:continue
            x,y=popout_positions.get(marker_index,(marker.x*factor,marker.y*factor)); status=statuses[0]
            canvas.create_oval(x-r,y-r,x+r,y+r,fill=status_palette.get(status,"#7f91a3"),outline="#ffffff",width=2,tags=("marker",))
            if self.map_show_labels.get(): canvas.create_text(x+r+6,y,text=self._map_display_name(marker.location_name),anchor="w",fill=ui_palette["success"],font="WayFinderMarkerLabel",tags=("marker_label",))
        if self._map_popout_status is not None:self._map_popout_status.set(self.map_status.get())
        if self._map_popout_location_counter is not None:self._map_popout_location_counter.set(f"Locations: {shown} / {total} visible")
        if self._map_popout_progress_detail is not None:self._map_popout_progress_detail.set(self.map_area_progress_detail.get())
        try: top=self._map_popout; top.title(f"WayFinder Map — {md.title}") if top is not None else None
        except tk.TclError: _ignored("intentional best-effort fallback")
        self._draw_route_overlay_on_canvas(canvas, md)
        self._draw_popout_area_progress()

