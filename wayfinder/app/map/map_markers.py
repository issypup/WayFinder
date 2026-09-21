"""Provide map markers support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

from .map_shared import *

class MapMarkersMixin:
    """Map subsystem responsibilities extracted from MapPageMixin."""
    def _ensure_map_marker_items(self, pack, md, factor):
        """Create Canvas marker primitives in small Tk batches.

        Large packs may contain thousands of Canvas objects (halo, segments, label,
        progress, completion per logical marker). Building them in one callback made
        Tk unresponsive even though image rendering itself was already threaded.
        This method now schedules at most 100 logical markers per callback and asks
        the normal state refresh to resume when construction completes.
        """
        if not hasattr(self,"_map_performance_ms"):
            self._map_performance_ms={}
        layout_key=(id(pack), md.name)
        markers=pack.markers_by_map.get(md.name, ())
        if self._map_marker_layout_key == layout_key and len(self._map_marker_items) == len(markers):
            return markers
        pending=getattr(self,"_map_marker_build_pending",None)
        if pending and pending.get("layout_key")==layout_key:
            return None

        self.map_canvas.delete("marker")
        self.map_canvas.delete("marker_label")
        self._map_marker_items.clear()
        self._map_marker_visual_state.clear()
        self._map_marker_layout_key=layout_key
        build_generation=int(getattr(self,"_map_marker_build_generation",0) or 0)+1
        self._map_marker_build_generation=build_generation
        build_started=time.perf_counter()
        self._map_marker_build_pending={"layout_key":layout_key,"generation":build_generation,"total":len(markers)}

        def create_one(idx,m):
            """Return create one."""
            tag=f"maploc_{idx}"
            halo=self.map_canvas.create_oval(0,0,0,0,fill="",outline="#ff9bb2",width=2,state="hidden",tags=(tag,"marker","marker_halo"))
            arcs=tuple(
                self.map_canvas.create_arc(0,0,0,0,start=0,extent=0,style="pieslice",fill="#7f91a3",outline="",width=0,state="hidden",tags=(tag,"marker","marker_segment"))
                for _ in range(6)
            )
            oval=self.map_canvas.create_oval(0,0,0,0,fill="#7f91a3",outline="#ffffff",width=1,tags=(tag,"marker"))
            progress=self.map_canvas.create_arc(0,0,0,0,start=90,extent=0,style="arc",outline="#e4c0ca",width=3,state="hidden",tags=(tag,"marker","marker_progress"))
            completion=self.map_canvas.create_text(0,0,text="",anchor="center",fill="#ffffff",font="WayFinderMarkerCount",state="hidden",tags=(tag,"marker","marker_completion"))
            label=self.map_canvas.create_text(0,0,text=self._map_display_name(m.location_name),anchor="w",fill=self._palette()["success"],font="WayFinderMarkerLabel",tags=(tag,"marker","marker_label"))
            self.map_canvas.tag_bind(tag,"<ButtonRelease-1>",lambda e,marker=m:self._map_marker_click(e,marker))
            self.map_canvas.tag_bind(tag,"<Double-Button-1>",lambda e,marker=m:self._map_marker_double_click(e,marker))
            self.map_canvas.tag_bind(tag,"<Button-3>",lambda e,marker=m:self._map_marker_context_menu(e,marker.member_names[0] if marker.member_names else marker.location_name))
            self.map_canvas.tag_bind(tag,"<Enter>",lambda e,marker=m:self._map_marker_enter(e,marker))
            self.map_canvas.tag_bind(tag,"<Motion>",lambda e,marker=m:self._map_marker_motion(e,marker))
            self.map_canvas.tag_bind(tag,"<Leave>",self._map_marker_leave)
            self._map_marker_items[idx]=(halo,oval,label,arcs,progress,completion)

        def build_chunk(start_index=0):
            """Return build chunk."""
            if getattr(self,"_closing",False) or self._map_marker_layout_key != layout_key or self._map_marker_build_generation != build_generation:
                return
            end_index=min(len(markers),start_index+100)
            for idx in range(start_index,end_index):
                create_one(idx,markers[idx])
            if hasattr(self,"map_load_strip") and end_index < len(markers):
                self.map_load_strip.set(f"{md.title} · {int(self.map_zoom.get())}% · preparing markers {end_index}/{len(markers)}")
            if end_index < len(markers):
                self.root.after(1,build_chunk,end_index)
                return
            self.map_canvas.delete("player_position")
            self._map_marker_build_pending=None
            self._map_performance_ms["marker_generation"]=round((time.perf_counter()-build_started)*1000.0,3)
            self.root.after_idle(lambda:self._refresh_map_markers(force_rebuild=False) if not self._closing else None)

        if not markers:
            self._map_marker_build_pending=None
            self._map_performance_ms["marker_generation"]=0.0
            return markers
        if not hasattr(self,"root"):
            # Headless/model tests do not own a Tk scheduler. Preserve the old
            # synchronous contract there while the real application remains chunked.
            for idx,m in enumerate(markers):
                create_one(idx,m)
            self.map_canvas.delete("player_position")
            self._map_marker_build_pending=None
            self._map_performance_ms["marker_generation"]=round((time.perf_counter()-build_started)*1000.0,3)
            return markers
        self.root.after_idle(build_chunk)
        return None

    def _map_marker_tooltip_text(self, marker):
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        """Handle map marker tooltip text."""
        state={x.name:x for x in self.snapshot.locations}
        if getattr(marker, "is_entrance_marker", False):
            status=self._map_entrance_marker_status(marker)
            lines=[f"{marker.location_name}", f"Entrance status: {status.replace('_',' ').title()}"]
            state={x.name:x for x in self.snapshot.locations}
            for index,name in enumerate(marker.member_names):
                section_status=self._map_entrance_section_status(marker,index,state)
                lines.append(f"{name}: {self._map_entrance_section_status_label(section_status)}")
            return "\n".join(lines)
        if getattr(marker, "is_exit_marker", False):
            # Exit-map objects are transition endpoints rather than AP checks.
            # When the reconstructed APWorld explicitly says entrance rando is
            # disabled, the assignment is not unknown: it is the vanilla/static
            # connection defined by the game. Only randomized or unadvertised
            # configurations should fall back to an unresolved assignment.
            entrance_rando = getattr(self.snapshot, "entrance_randomization_enabled", None)
            if entrance_rando is False:
                return f"{marker.location_name}\nExit/transition marker • vanilla assignment (entrance randomization off)"
            if entrance_rando is True:
                return f"{marker.location_name}\nExit/transition marker • assignment unknown / not yet discovered"
            return f"{marker.location_name}\nExit/transition marker • assignment state unavailable"
        if marker.is_group:
            # Variable(s): `counts` (counts); named state retained for the surrounding calculation or subsequent calls.
            counts={"reachable":0,"glitched":0,"out_of_logic":0,"checked":0,"ignored":0,"non_progression":0,"unknown":0}
            # Variable(s): `active_members` (active members); named state retained for the surrounding calculation or subsequent calls.
            active_members=0
            # Variable(s): `unknown_reasons` (unknown reasons); named state retained for the surrounding calculation or subsequent calls.
            unknown_reasons=[]
            # Loop variable(s): `member_index` (member index), `name` (name); each iteration represents the next value from the iterable below.
            for member_index,name in enumerate(marker.member_names):
                # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
                loc=self._map_marker_member_location(marker,member_index,state)
                if loc is None:
                    # Static map packs can contain optional checks that the current
                    # generator options removed. They are not Unknown; they simply
                    # do not exist in this seed and are omitted from the marker.
                    continue
                active_members+=1
                # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
                status=self._map_effective_location_status(loc)
                # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
                if status not in counts: status="unknown"
                counts[status]+=1
                if status=="unknown" and getattr(loc,"unknown_reason",""):
                    unknown_reasons.append(f"{name}: {loc.unknown_reason}")
            if active_members == 0:
                return f"{marker.location_name}\nNot included in current seed"
            # Variable(s): `done` (done); named state retained for the surrounding calculation or subsequent calls.
            done=counts["checked"]
            # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
            current="Checked" if done==active_members else ("Partially checked" if done else "Active")
            # Variable(s): `parts` (parts); named state retained for the surrounding calculation or subsequent calls.
            parts=[f"{marker.location_name}",f"Status: {current} • {done}/{active_members} checked"]
            # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
            detail=[]
            # Loop variable(s): `key` (key), `label` (label); each iteration represents the next value from the iterable below.
            for key,label in (("reachable","Reachable"),("glitched","Glitch-only"),("out_of_logic","Out of logic"),("checked","Checked"),("ignored","Ignored"),("non_progression","Non-progression / untracked"),("unknown","Unknown")):
                if counts[key]: detail.append(f"{label}: {counts[key]}")
            if detail: parts.append(" • ".join(detail))
            if unknown_reasons: parts.append("Unknown reason: " + " | ".join(unknown_reasons[:3]))
            return "\n".join(parts)
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name=marker.location_name
        # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
        loc=self._map_marker_member_location(marker,0,state)
        if loc is None:
            return f"{self._map_display_name(name)}\nNot included in current seed"
        # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
        status=self._map_effective_location_status(loc)
        # Variable(s): `hint` (hint); named state retained for the surrounding calculation or subsequent calls.
        hint=(f"\nHint: {getattr(loc,'hint_status','unspecified').replace('_',' ').title()}" if getattr(loc,"hinted",False) else "")
        # Variable(s): `reason` (reason); named state retained for the surrounding calculation or subsequent calls.
        reason=(f"\nReason: {loc.unknown_reason}" if status=="unknown" and getattr(loc,"unknown_reason","") else "")
        if status=="non_progression":
            runtime_reason=str(getattr(loc,"unknown_reason","") or "")
            if runtime_reason.startswith("Location ") and ":" in runtime_reason:
                reason=f"\nReason: Known check, but its APWorld access rule is currently untracked by the native adapter.\nDetail: {runtime_reason}"
            else:
                reason="\nReason: Present in the seed, but not represented in the reconstructed APWorld logic graph."
        return f"{self._map_display_name(name)}\nStatus: {status.replace('_',' ').title()}{reason}{hint}"

    def _hide_map_tooltip(self):
        # Variable(s): `tip` (tip); named state retained for the surrounding calculation or subsequent calls.
        """Handle hide map tooltip."""
        tip=getattr(self,"_map_tooltip",None)
        self._map_tooltip=None
        if tip is not None:
            try: tip.destroy()
            except tk.TclError: _ignored("intentional best-effort fallback")

    def _show_map_tooltip(self,event,marker):
        """Handle show map tooltip."""
        if not self.map_show_tooltips.get():
            self._hide_map_tooltip(); return
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        text=self._map_marker_tooltip_text(marker)
        self._hide_map_tooltip()
        # Variable(s): `tip` (tip); named state retained for the surrounding calculation or subsequent calls.
        tip=tk.Toplevel(self.root)
        self._map_tooltip=tip
        tip.wm_overrideredirect(True)
        try: tip.wm_attributes("-topmost",True)
        except tk.TclError: _ignored("intentional best-effort fallback")
        tk.Label(tip,text=text,justify="left",anchor="w",background=self._palette()["card"],foreground=self._palette()["fg"],relief="solid",borderwidth=1,padx=8,pady=6,font="WayFinderSmall",highlightbackground=self._palette()["border"]).pack()
        tip.geometry(f"+{event.x_root+14}+{event.y_root+14}")

    def _map_marker_enter(self,event,marker):
        # Variable(s): `text` (text); named state retained for the surrounding calculation or subsequent calls.
        """Handle map marker enter."""
        text=self._map_marker_tooltip_text(marker)
        self.map_hover.set(text.replace("\n","  •  "))
        self._show_map_tooltip(event,marker)

    def _map_marker_motion(self,event,marker):
        # Variable(s): `tip` (tip); named state retained for the surrounding calculation or subsequent calls.
        """Handle map marker motion."""
        tip=getattr(self,"_map_tooltip",None)
        if tip is not None:
            try: tip.geometry(f"+{event.x_root+14}+{event.y_root+14}")
            except tk.TclError: self._map_tooltip=None

    def _map_marker_leave(self,_event=None):
        """Handle map marker leave."""
        self._hide_map_tooltip()
        self.map_hover.set("Single-click selects • Double-click opens Path Explorer • Right-click for actions • Esc / empty-map click clears selection")

    def _map_marker_display_positions(self, markers, factor, radius):
        """Return stable screen-space marker positions with local collision spreading.

        PopTracker packs frequently place multiple logical markers at nearly the
        same source coordinate.  At WayFinder's marker sizes those circles can
        overlap enough that only the top-most Canvas item is practically
        clickable.  This helper detects connected groups whose centres are
        closer than the current marker diameter plus a small click gap and
        distributes only those groups around their local centroid.

        Offsets are intentionally calculated in *screen pixels*, not source map
        coordinates, so the behaviour automatically adapts to zoom and marker
        size without modifying or rewriting the imported pack.
        """
        if not markers:
            return {}
        base={idx:(float(marker.x)*factor,float(marker.y)*factor) for idx,marker in enumerate(markers)}
        minimum_distance=max(10.0,float(radius)*2.0+5.0)
        minimum_distance_sq=minimum_distance*minimum_distance

        # Only neighbouring spatial cells can contain overlapping markers.
        # This avoids a quadratic scan of every pair on large map pages.
        import math
        neighbours={idx:set() for idx in range(len(markers))}
        cells={}
        for right,(rx,ry) in base.items():
            cx,cy=math.floor(rx/minimum_distance),math.floor(ry/minimum_distance)
            for gx in range(cx-1,cx+2):
                for gy in range(cy-1,cy+2):
                    for left in cells.get((gx,gy),()):
                        lx,ly=base[left]
                        dx=lx-rx; dy=ly-ry
                        if dx*dx+dy*dy < minimum_distance_sq:
                            neighbours[left].add(right); neighbours[right].add(left)
            cells.setdefault((cx,cy),[]).append(right)

        positions=dict(base)
        visited=set()
        import math
        for seed in range(len(markers)):
            if seed in visited:
                continue
            stack=[seed]; component=[]; visited.add(seed)
            while stack:
                current=stack.pop(); component.append(current)
                for nxt in neighbours[current]:
                    if nxt not in visited:
                        visited.add(nxt); stack.append(nxt)
            if len(component)<=1:
                continue

            component.sort()
            centre_x=sum(base[i][0] for i in component)/len(component)
            centre_y=sum(base[i][1] for i in component)/len(component)

            # Use one or more deterministic rings.  Six markers per ring keeps
            # adjacent circles comfortably separated while preventing a dense
            # island/entrance cluster from being thrown far from its real area.
            remaining=list(component)
            ring_number=1
            while remaining:
                ring=remaining[:6*ring_number]
                remaining=remaining[len(ring):]
                count=len(ring)
                ring_radius=max(minimum_distance, minimum_distance*count/(2.0*math.pi))*ring_number
                # Rotate even-sized groups by half a slot so two-marker clusters
                # spread diagonally rather than sitting directly on labels.
                start_angle=(-math.pi/2.0)+(math.pi/count if count%2==0 else 0.0)
                for slot,idx in enumerate(ring):
                    angle=start_angle+(2.0*math.pi*slot/count)
                    positions[idx]=(centre_x+math.cos(angle)*ring_radius, centre_y+math.sin(angle)*ring_radius)
                ring_number+=1
        return positions

    def _refresh_map_markers(self, force_rebuild=False):
        """Update persistent Canvas markers in-place; never re-decode the background."""
        marker_started=time.perf_counter()
        if not hasattr(self,"map_canvas"):
            print("[MAP-DEBUG] marker refresh ABORT: no map_canvas", flush=True)
            return
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        pack=self.active_map_pack; md=self._current_map_def()
        if not pack or not md:
            print(f"[MAP-DEBUG] marker refresh ABORT: pack={getattr(pack,'display_name',None)!r} map_def={getattr(md,'title',None)!r} selector={self.map_selector_var.get() if hasattr(self,'map_selector_var') else None!r}", flush=True)
            return
        # Variable(s): `expected` (expected); named state retained for the surrounding calculation or subsequent calls.
        expected=asset_key(pack,md.image,int(self.map_zoom.get()))
        if self.map_background_key != expected or self.map_photo is None:
            # Coalesce marker-triggered render requests.  A scheduled request is
            # already represented by _map_requested_key even before the worker
            # sets map_rendering_key, so repeated live snapshots must not enqueue
            # the same background forever.
            requested=getattr(self, '_map_requested_key', None)
            pending=(self.map_rendering_key == expected or (requested == expected and self._map_zoom_after_id is not None))
            if not pending and getattr(self, '_map_failed_key', None) != expected:
                print(f"[MAP-DEBUG] marker refresh requesting background render expected={expected!r}", flush=True)
                self._request_map_render(preserve_view=True, delay=70)
            return
        # Variable(s): `factor` (factor); named state retained for the surrounding calculation or subsequent calls.
        factor=int(self.map_zoom.get())/100.0
        if force_rebuild:
            self._map_marker_visual_state.clear()
        # Variable(s): `markers` (markers); named state retained for the surrounding calculation or subsequent calls.
        markers=self._ensure_map_marker_items(pack,md,factor)
        if markers is None:
            return
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state={x.name:x for x in self.snapshot.locations}
        # Variable(s): `canonical` (canonical); named state retained for the surrounding calculation or subsequent calls.
        canonical={}
        # Loop variable(s): `name` (name), `loc` (loc); each iteration represents the next value from the iterable below.
        for name,loc in state.items():
            canonical[name]=self._map_effective_location_status(loc)
        # Variable(s): `previous_canonical` (previous canonical); named state retained for the surrounding calculation or subsequent calls.
        previous_canonical=self._map_canonical_marker_state
        # Variable(s): `changed` (changed); named state retained for the surrounding calculation or subsequent calls.
        changed={name for name in (canonical.keys() | previous_canonical.keys()) if canonical.get(name) != previous_canonical.get(name)}
        self._map_canonical_marker_state=canonical
        self._map_changed_locations=changed
        if changed:
            print(f"[MAP-DEBUG] marker delta seq={getattr(self.snapshot,'snapshot_sequence',0)} changed_count={len(changed)} changed={sorted(changed)[:12]}", flush=True)
        # Zero-delta snapshots are intentionally silent.  They are normal live
        # polling and must not flood the console or provoke extra render work.
        # Variable(s): `palette` (palette); named state retained for the surrounding calculation or subsequent calls.
        palette={k:v["color"] for k,v in STATUS_VISUALS.items()}
        # Variable(s): `size_scale` (size scale); named state retained for the surrounding calculation or subsequent calls.
        size_scale={"Small":0.72,"Medium":1.0,"Large":1.35}.get(self.map_marker_size.get(),1.0)
        # Variable(s): `search_q` (search q); named state retained for the surrounding calculation or subsequent calls.
        search_q=self.search_var.get().strip() if hasattr(self,"search_var") else ""
        # Variable(s): `do_highlight` (do highlight); named state retained for the surrounding calculation or subsequent calls.
        do_highlight=bool(self.map_highlight_search.get() and search_q)
        # Variable(s): `shown` (shown); named state retained for the surrounding calculation or subsequent calls.
        shown=0
        # Variable(s): `statuses` (statuses); named state retained for the surrounding calculation or subsequent calls.
        statuses={}
        # Variable(s): `r` (r); named state retained for the surrounding calculation or subsequent calls.
        r=max(3.0,md.location_size*factor/2.0*size_scale)
        # Spread only markers that would otherwise overlap at this zoom/size.
        # Source coordinates remain untouched; this is a display-only layout.
        display_positions=self._map_marker_display_positions(markers,factor,r)
        # Variable(s): `border` (border); named state retained for the surrounding calculation or subsequent calls.
        border=max(1,int(md.location_border_thickness))
        # Variable(s): `label_font` (label font); named state retained for the surrounding calculation or subsequent calls.
        label_font="WayFinderMarkerLabel"
        hidden_members=self._map_hidden_members(md)
        # Loop variable(s): `idx` (index), `m` (m); each iteration represents the next value from the iterable below.
        for idx,m in enumerate(markers):
            if not force_rebuild and changed and not any(n in changed for n in m.member_names) and idx in self._map_marker_visual_state:
                # Marker lookup structures are cached by pack; unchanged groups do
                # not need Canvas reconfiguration when one check changes.
                # Variable(s): `old_states` (old states); named state retained for the surrounding calculation or subsequent calls.
                old_states=[self._map_last_statuses.get(n,"unknown") for n in m.member_names]
                # Variable(s): `visible_old_states` (visible old states); named state retained for the surrounding calculation or subsequent calls.
                visible_old_states=[v for v in old_states if v != "not_in_seed"]
                if any(self.map_status_visible.get(v, self.map_status_visible["unknown"]).get() for v in visible_old_states):
                    shown += sum(1 for v in visible_old_states if self.map_status_visible.get(v, self.map_status_visible["unknown"]).get())
                statuses.update({n:self._map_last_statuses.get(n,"unknown") for n in m.member_names})
                continue
            # Variable(s): `hidden_members` (hidden members); named state retained for the surrounding calculation or subsequent calls.
            if m.member_names and all(self._resolve_map_location_name(name,state) in hidden_members or name in hidden_members for name in m.member_names):
                # Variable(s): `halo` (halo), `oval` (oval), `label` (label), `arcs` (arcs), `progress` (progress), `completion` (completion); named state retained for the surrounding calculation or subsequent calls.
                halo,oval,label,arcs,progress,completion=self._map_marker_items[idx]
                # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
                for item in (halo,oval,label,progress,completion,*arcs): self.map_canvas.itemconfigure(item,state="hidden")
                continue
            # Variable(s): `member_states` (member states); named state retained for the surrounding calculation or subsequent calls.
            member_states=[]
            # Variable(s): `member_locations` (member locations); named state retained for the surrounding calculation or subsequent calls.
            member_locations=[]
            # Variable(s): `active_member_names` (active member names); named state retained for the surrounding calculation or subsequent calls.
            active_member_names=[]
            if getattr(m, "is_entrance_marker", False):
                # PopTracker entrance overview nodes expose tracker-only sections such
                # as Can Enter/Can Complete. They are not Archipelago locations, so
                # keep one marker per entrance visible and color it from native
                # entrance state where a trustworthy name match is available.
                entrance_status=self._map_entrance_marker_status(m)
                member_states=[entrance_status]
                active_member_names=[m.location_name]
                statuses[m.location_name]=entrance_status
            elif getattr(m, "is_exit_marker", False):
                # Exit/transition endpoints may be driven entirely by PopTracker Lua.
                # They are still real map objects and must not disappear merely
                # because there is no corresponding AP location in the seed.
                member_states=["unknown"]
                active_member_names=[m.location_name]
                statuses[m.location_name]="unknown"
            # Loop variable(s): `member_index` (member index), `member_name` (member name); each iteration represents the next value from the iterable below.
            for member_index,member_name in enumerate(() if getattr(m, "is_synthetic_marker", False) else m.member_names):
                # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
                loc=self._map_marker_member_location(m,member_index,state)
                if loc is None:
                    # The pack describes a possible location, but the current AP
                    # seed did not generate it. Do not render it as Unknown.
                    statuses[member_name]="not_in_seed"
                    continue
                member_locations.append(loc)
                active_member_names.append(member_name)
                # Variable(s): `member_status` (member status); named state retained for the surrounding calculation or subsequent calls.
                member_status=self._map_effective_location_status(loc)
                if member_status not in self.map_status_visible:
                    # Variable(s): `member_status` (member status); named state retained for the surrounding calculation or subsequent calls.
                    member_status="unknown"
                statuses[member_name]=member_status
                member_states.append(member_status)
            if member_states and m.location_name and m.location_name not in active_member_names:
                active_member_names.append(m.location_name)
            if not member_states:
                # Variable(s): `halo` (halo), `oval` (oval), `label` (label), `arcs` (arcs), `progress` (progress), `completion` (completion); named state retained for the surrounding calculation or subsequent calls.
                halo,oval,label,arcs,progress,completion=self._map_marker_items[idx]
                # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
                for item in (halo,oval,label,progress,completion,*arcs): self.map_canvas.itemconfigure(item,state="hidden")
                self._map_marker_visual_state[idx]=("not_in_seed",)
                continue
            # Grouped tracker area markers advertise every distinct visible state at once.
            # Two states split the marker 50/50; three states split it into thirds.
            # Variable(s): `priority` (priority); named state retained for the surrounding calculation or subsequent calls.
            priority=("reachable","glitched","out_of_logic","non_progression","unknown","ignored","checked")
            # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
            status=next((v for v in priority if v in member_states), "unknown")
            # Variable(s): `segment_statuses` (segment statuses); named state retained for the surrounding calculation or subsequent calls.
            segment_statuses=tuple(v for v in priority if v in member_states and bool(self.map_status_visible[v].get()))
            # Variable(s): `checked_count` (checked count); named state retained for the surrounding calculation or subsequent calls.
            checked_count=sum(1 for v in member_states if v=="checked")
            # Variable(s): `group_total` (group total); named state retained for the surrounding calculation or subsequent calls.
            group_total=max(1,len(member_states))
            # Variable(s): `fully_checked` (fully checked); named state retained for the surrounding calculation or subsequent calls.
            fully_checked=bool(m.is_group and checked_count==group_total)
            # Variable(s): `visible` (visible); named state retained for the surrounding calculation or subsequent calls.
            visible=bool(segment_statuses) and not (fully_checked and self.map_hide_checked_groups.get())
            if visible: shown += sum(1 for v in member_states if self.map_status_visible[v].get())
            # Variable(s): `x` (horizontal x-coordinate); named state retained for the surrounding calculation or subsequent calls.
            x,y=display_positions.get(idx,(m.x*factor,m.y*factor))
            # Variable(s): `is_match` (is match); named state retained for the surrounding calculation or subsequent calls.
            is_match=do_highlight and any(self._fuzzy_match(search_q,n) for n in active_member_names)
            # Variable(s): `is_selected` (is selected); named state retained for the surrounding calculation or subsequent calls.
            is_selected=(self.map_selected_location in active_member_names)
            # Variable(s): `hinted_members` (hinted members); named state retained for the surrounding calculation or subsequent calls.
            hinted_members=[loc for loc in member_locations if loc and getattr(loc,"hinted",False) and getattr(loc,"status","") != "checked"]
            # Variable(s): `is_hinted` (is hinted); named state retained for the surrounding calculation or subsequent calls.
            is_hinted=bool(hinted_members)
            # Variable(s): `draw_r` (draw r); named state retained for the surrounding calculation or subsequent calls.
            draw_r=r*(1.18 if is_selected else (1.08 if is_match else (1.04 if is_hinted and self._map_hint_phase else 1.0)))
            # Variable(s): `outline` (outline); named state retained for the surrounding calculation or subsequent calls.
            outline="#ffffff" if is_selected else ("#ffe36e" if is_match else ("#efb5c7" if is_hinted else "#ffffff"))
            # Variable(s): `width` (width); named state retained for the surrounding calculation or subsequent calls.
            width=max(4,border+3) if is_selected else (max(3,border+2) if is_match else border)
            # Variable(s): `halo` (halo), `oval` (oval), `label` (label), `arcs` (arcs), `progress` (progress), `completion` (completion); named state retained for the surrounding calculation or subsequent calls.
            halo,oval,label,arcs,progress,completion=self._map_marker_items[idx]
            # Variable(s): `marker_state` (marker state); named state retained for the surrounding calculation or subsequent calls.
            marker_state=(status,segment_statuses,visible,is_match,is_selected,is_hinted,self._map_hint_phase,round(r,3),round(x,2),round(y,2),border,bool(self.map_show_labels.get()),label_font,m.is_group,checked_count,group_total,bool(self.map_hide_checked_groups.get()))
            if self._map_marker_visual_state.get(idx) != marker_state:
                # Variable(s): `halo_r` (halo r); named state retained for the surrounding calculation or subsequent calls.
                halo_r=draw_r+5
                self.map_canvas.coords(halo,x-halo_r,y-halo_r,x+halo_r,y+halo_r)
                self.map_canvas.itemconfigure(halo,outline=("#ff9bb2" if is_selected else ("#ffe36e" if is_match else "#efb5c7")),width=(3 if is_selected else 2),state=("normal" if visible and (is_selected or is_match or (is_hinted and self._map_hint_phase)) else "hidden"))
                self.map_canvas.coords(oval,x-draw_r,y-draw_r,x+draw_r,y+draw_r)
                if m.is_group:
                    # Variable(s): `progress_r` (progress r); named state retained for the surrounding calculation or subsequent calls.
                    progress_r=draw_r+2
                    self.map_canvas.coords(progress,x-progress_r,y-progress_r,x+progress_r,y+progress_r)
                    self.map_canvas.itemconfigure(progress,extent=(-360.0*checked_count/group_total),outline="#e4c0ca",width=max(2,border+2),state=("normal" if visible and 0 < checked_count < group_total else "hidden"))
                    self.map_canvas.coords(completion,x,y)
                    self.map_canvas.itemconfigure(completion,text=f"{checked_count}/{group_total}",font="WayFinderMarkerCount",state=("normal" if visible else "hidden"))
                else:
                    self.map_canvas.itemconfigure(progress,state="hidden")
                    self.map_canvas.itemconfigure(completion,state="hidden")
                if m.is_group and len(segment_statuses) > 1:
                    self.map_canvas.itemconfigure(oval,fill="",outline=outline,width=width,state=("normal" if visible else "hidden"))
                    # Variable(s): `extent` (extent); named state retained for the surrounding calculation or subsequent calls.
                    extent=360.0/len(segment_statuses)
                    # Loop variable(s): `seg_idx` (seg idx), `arc` (arc); each iteration represents the next value from the iterable below.
                    for seg_idx,arc in enumerate(arcs):
                        if seg_idx < len(segment_statuses):
                            # Variable(s): `seg_status` (seg status); named state retained for the surrounding calculation or subsequent calls.
                            seg_status=segment_statuses[seg_idx]
                            self.map_canvas.coords(arc,x-draw_r,y-draw_r,x+draw_r,y+draw_r)
                            self.map_canvas.itemconfigure(arc,start=90.0-seg_idx*extent,extent=-extent,fill=palette[seg_status],state=("normal" if visible else "hidden"))
                        else:
                            self.map_canvas.itemconfigure(arc,state="hidden")
                    self.map_canvas.tag_raise(oval)
                    self.map_canvas.tag_raise(progress)
                    self.map_canvas.tag_raise(completion)
                    self.map_canvas.tag_raise(label)
                    self.map_canvas.tag_raise(halo)
                else:
                    # Loop variable(s): `arc` (arc); each iteration represents the next value from the iterable below.
                    for arc in arcs:
                        self.map_canvas.itemconfigure(arc,state="hidden")
                    # Variable(s): `single_status` (single status); named state retained for the surrounding calculation or subsequent calls.
                    single_status=segment_statuses[0] if segment_statuses else status
                    self.map_canvas.itemconfigure(oval,fill=palette[single_status],outline=outline,width=width,state=("normal" if visible else "hidden"))
                self.map_canvas.coords(label,x+draw_r+6,y)
                self.map_canvas.itemconfigure(label,text=self._map_display_name(m.location_name),font=label_font,fill=("#ffffff" if is_selected else ("#f6dce4" if is_hinted else self._palette()["success"])),state=("normal" if visible and self.map_show_labels.get() else "hidden"))
                self._map_marker_visual_state[idx]=marker_state
        self._map_last_statuses=statuses
        # Variable(s): `total` (total); named state retained for the surrounding calculation or subsequent calls.
        total=0
        # Loop variable(s): `marker` (marker); each iteration represents the next value from the iterable below.
        for marker in markers:
            # Loop variable(s): `member_index` (member index), `_member_name` (member name); each iteration represents the next value from the iterable below.
            for member_index,_member_name in enumerate(marker.member_names):
                if self._map_marker_member_location(marker,member_index,state) is not None:
                    total += 1
        if hasattr(self,"map_location_counter"):
            self.map_location_counter.set(f"Locations: {shown} / {total} visible")
        # Variable(s): `hidden` (hidden); named state retained for the surrounding calculation or subsequent calls.
        hidden=sum(1 for v in self.map_status_visible.values() if not v.get())
        # Variable(s): `suffix` (suffix); named state retained for the surrounding calculation or subsequent calls.
        suffix=f" • {shown}/{total} locations visible" + (f" • {hidden} status filter{'s' if hidden!=1 else ''} hidden" if hidden else "")
        # Variable(s): `base` (base); named state retained for the surrounding calculation or subsequent calls.
        base=f"{md.title} • {int(self.map_zoom.get())}% • middle-drag to pan • Home fits map"
        if self.map_background_key==expected: self.map_status.set(base+suffix)
        if self._map_popout_status is not None: self._map_popout_status.set(self.map_status.get())
        if self._map_popout_location_counter is not None: self._map_popout_location_counter.set(f"Locations: {shown} / {total} visible")
        if self._map_popout_progress_detail is not None: self._map_popout_progress_detail.set(self.map_area_progress_detail.get())
        if self._map_popout_canvas is not None: self.root.after_idle(self._refresh_popout_map)
        # live player position is rendered above check markers. Negative coords
        # were already discarded by the runtime transport per the map-position contract.
        self.map_canvas.delete("player_position")
        # Variable(s): `current_map_index` (current map index); named state retained for the surrounding calculation or subsequent calls.
        current_map_index=next((i for i,mdef in enumerate(pack.maps) if mdef.name==md.name), -1)
        if int(getattr(self.snapshot,"player_position_map_index",-1) if getattr(self.snapshot,"player_position_map_index",-1) is not None else -1) == current_map_index:
            # Loop variable(s): `icon` (icon); each iteration represents the next value from the iterable below.
            for icon in list(getattr(self.snapshot,"player_position_icons",[]) or []):
                try:
                    # Variable(s): `px` (px); named state retained for the surrounding calculation or subsequent calls.
                    px=float(icon.get("x"))*factor; py=float(icon.get("y"))*factor
                except Exception: continue
                # Variable(s): `rr` (rr); named state retained for the surrounding calculation or subsequent calls.
                rr=max(7.0,r*0.70)
                self.map_canvas.create_oval(px-rr,py-rr,px+rr,py+rr,fill="#f4fbff",outline="#f58aa5",width=3,tags=("player_position",))
                self.map_canvas.create_oval(px-2.2,py-2.2,px+2.2,py+2.2,fill="#a84263",outline="",tags=("player_position",))
        # Route geometry is a transient Canvas layer. Marker rebuilds happen after
        # map/zoom changes and previously could leave a checked Route overlay with
        # nothing visible until the option was toggled again. Repaint it every time
        # the marker layer is refreshed, then keep the live player icon uppermost.
        self._draw_route_overlay()
        self.map_canvas.tag_raise("player_position")
        self._last_marker_update_seconds=max(0.0,time.perf_counter()-marker_started)
        self._map_performance_ms["marker_state_update"]=round(self._last_marker_update_seconds*1000.0,3)
        self._sync_run_context_from_ui()
        self._update_diagnostic_timings()
        self._schedule_hint_pulse()
        self._refresh_minimap()

