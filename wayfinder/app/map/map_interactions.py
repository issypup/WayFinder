"""Provide map interactions support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

from .map_shared import *

class MapInteractionsMixin:
    """Map subsystem responsibilities extracted from MapPageMixin."""
    def _select_map_location(self,name):
        """Select a map location without navigating away from the Map page."""
        if getattr(self,"run_context",None) is not None:
            self.run_context.selected_check=str(name or "")
        self.map_selected_location=(name or "").strip()
        if self.map_selected_location and hasattr(self,"path_var"):
            self.path_var.set(self.map_selected_location)
        if hasattr(self,"map_canvas"):
            self._refresh_map_markers()
        # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
        loc=self._map_location(self.map_selected_location)
        if loc and hasattr(self,"map_hover"):
            self.map_hover.set(f"Selected: {loc.name}  •  {self._map_effective_location_status(loc).replace('_',' ').title()}  •  Double-click for Path Explorer")
        elif self.map_selected_location and hasattr(self,"map_hover"):
            self.map_hover.set(f"Selected: {self.map_selected_location}  •  Double-click for Path Explorer")

    def _close_map_group_popup(self):
        # Variable(s): `popup` (popup); named state retained for the surrounding calculation or subsequent calls.
        """Handle close map group popup."""
        popup=getattr(self, "_map_group_popup", None)
        self._map_group_popup=None
        self._map_group_popup_names=[]
        self._map_group_popup_listbox=None
        self._map_group_popup_count_var=None
        self._map_group_popup_marker=None
        if popup is not None:
            try: popup.destroy()
            except tk.TclError: _ignored("intentional best-effort fallback")

    def _refresh_map_group_popup(self):
        """Keep an open grouped-marker popup synchronized with live native snapshots."""
        # Variable(s): `popup` (popup); named state retained for the surrounding calculation or subsequent calls.
        popup=getattr(self, "_map_group_popup", None)
        # Variable(s): `lb` (lb); named state retained for the surrounding calculation or subsequent calls.
        lb=getattr(self, "_map_group_popup_listbox", None)
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=list(getattr(self, "_map_group_popup_names", []) or [])
        if popup is None or lb is None or not names:
            return
        try:
            if not popup.winfo_exists():
                self._close_map_group_popup()
                return
        except tk.TclError:
            self._close_map_group_popup()
            return

        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state={x.name:x for x in self.snapshot.locations}
        # Variable(s): `checked` (checked); named state retained for the surrounding calculation or subsequent calls.
        marker=getattr(self,"_map_group_popup_marker",None)
        is_entrance=bool(marker is not None and getattr(marker,"is_entrance_marker",False))
        checked=sum(1 for index,_name in enumerate(names) if getattr(self._map_marker_member_location(marker,index,state), "status", "") == "checked") if not is_entrance else 0
        # Variable(s): `count_var` (count var); named state retained for the surrounding calculation or subsequent calls.
        count_var=getattr(self, "_map_group_popup_count_var", None)
        if count_var is not None:
            if is_entrance:
                entrance_status=self._map_entrance_marker_status(marker)
                count_var.set(f"Entrance status: {entrance_status.replace('_',' ').title()}")
            else:
                count_var.set(f"{checked} / {len(names)} checked")

        try:
            # Variable(s): `selection` (selection); named state retained for the surrounding calculation or subsequent calls.
            selection=lb.curselection()
            # Variable(s): `selected_index` (selected index); named state retained for the surrounding calculation or subsequent calls.
            selected_index=selection[0] if selection else None
            # Variable(s): `yview` (yview); named state retained for the surrounding calculation or subsequent calls.
            yview=lb.yview()
            lb.delete(0, "end")
            # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
            for index,name in enumerate(names):
                if is_entrance:
                    status=self._map_entrance_section_status(marker,index,state)
                    label=self._map_entrance_section_status_label(status)
                else:
                    # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
                    loc=self._map_marker_member_location(marker,index,state)
                    # Resolve grouped PopTracker entries with the exact same AP-ID-aware
                    # path used by the marker renderer. Display labels such as "Great
                    # Fairy" or dungeon room names are not guaranteed to equal the
                    # APWorld's canonical location name.
                    status=(self._map_effective_location_status(loc) if loc else "unknown")
                    label=status.replace('_',' ').title()
                lb.insert("end", f"{name}  •  {label}")
            if selected_index is not None and selected_index < len(names):
                lb.selection_set(selected_index)
                lb.activate(selected_index)
            if yview:
                lb.yview_moveto(yview[0])
        except tk.TclError:
            self._close_map_group_popup()

    def _show_map_group_popup(self, event, marker):
        """Scrollable area/check list for tracker parent markers with section children."""
        self._close_map_group_popup()
        # Variable(s): `popup` (popup); named state retained for the surrounding calculation or subsequent calls.
        popup=tk.Toplevel(self.root)
        popup.configure(bg=self._palette()["bg"])
        self._map_group_popup=popup
        popup.title(marker.location_name or "Map area")
        popup.transient(self.root)
        popup.resizable(True, True)
        popup.minsize(360, 180)
        popup.geometry(f"460x360+{self.root.winfo_pointerx()+12}+{self.root.winfo_pointery()+12}")
        # Variable(s): `outer` (outer); named state retained for the surrounding calculation or subsequent calls.
        outer=ttk.Frame(popup,style="Card.TFrame",padding=10); outer.pack(fill="both",expand=True,padx=10,pady=10)
        # Variable(s): `state` (state); named state retained for the surrounding calculation or subsequent calls.
        state={x.name:x for x in self.snapshot.locations}
        # Variable(s): `names` (names); named state retained for the surrounding calculation or subsequent calls.
        names=list(marker.member_names)
        # Variable(s): `checked` (checked); named state retained for the surrounding calculation or subsequent calls.
        is_entrance=bool(getattr(marker,"is_entrance_marker",False))
        checked=sum(1 for index,_name in enumerate(names) if getattr(self._map_marker_member_location(marker,index,state),"status","")=="checked") if not is_entrance else 0
        ttk.Label(outer,text=marker.location_name,style="CardHeading.TLabel").pack(anchor="w")
        if is_entrance:
            entrance_status=self._map_entrance_marker_status(marker)
            count_text=f"Entrance status: {entrance_status.replace('_',' ').title()}"
        else:
            count_text=f"{checked} / {len(names)} checked"
        self._map_group_popup_count_var=tk.StringVar(value=count_text)
        ttk.Label(outer,textvariable=self._map_group_popup_count_var,style="CardMuted.TLabel").pack(anchor="w",pady=(0,6))
        # Variable(s): `body` (body); named state retained for the surrounding calculation or subsequent calls.
        body=ttk.Frame(outer,style="Card.TFrame"); body.pack(fill="both",expand=True)
        # Variable(s): `lb` (lb); named state retained for the surrounding calculation or subsequent calls.
        lb=tk.Listbox(body,activestyle="dotbox",exportselection=False,font=("Segoe UI",self.font_size.get()),bg=self._palette()["panel"],fg=self._palette()["fg"],selectbackground=self._palette()["select"],selectforeground=self._palette()["fg"],highlightthickness=1,highlightbackground=self._palette()["accent"],highlightcolor=self._palette()["accent_hover"],relief="flat")
        # Variable(s): `sy` (sy); named state retained for the surrounding calculation or subsequent calls.
        sy=ttk.Scrollbar(body,orient="vertical",command=lb.yview); lb.configure(yscrollcommand=sy.set)
        sy.pack(side="right",fill="y"); lb.pack(side="left",fill="both",expand=True)
        self._map_group_popup_names=names
        self._map_group_popup_listbox=lb
        self._map_group_popup_marker=marker
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for index,name in enumerate(names):
            if is_entrance:
                status=self._map_entrance_section_status(marker,index,state)
                label=self._map_entrance_section_status_label(status)
            else:
                # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
                loc=self._map_marker_member_location(marker,index,state)
                # Use section IDs before falling back to the PopTracker display name.
                status=(self._map_effective_location_status(loc) if loc else "unknown")
                label=status.replace('_',' ').title()
            lb.insert("end",f"{name}  •  {label}")
        # /**
        #  * Function: choose
        #  * Purpose: Perform the choose operation while keeping the surrounding subsystem state consistent.
        #  * @param _e: E supplied by the caller; see type hints and call sites for domain constraints.
        #  * @param open_path: Open path supplied by the caller; see type hints and call sites for domain constraints.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def choose(_e=None, open_path=False):
            """Handle choose."""
            if is_entrance:
                return
            # Variable(s): `sel` (sel); named state retained for the surrounding calculation or subsequent calls.
            sel=lb.curselection()
            if not sel:return
            # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
            index=sel[0]
            name=names[index]
            # Select/open the canonical APWorld location when this grouped marker
            # uses PopTracker aliases or ref-only dungeon sections.
            live_state={x.name:x for x in self.snapshot.locations}
            loc=self._map_marker_member_location(marker,index,live_state)
            canonical=getattr(loc,"name","") if loc is not None else name
            self._select_map_location(canonical)
            if open_path:
                self.open_path(canonical); self._close_map_group_popup()
        lb.bind("<<ListboxSelect>>",choose)
        lb.bind("<Double-Button-1>",lambda e:choose(e,True))
        popup.protocol("WM_DELETE_WINDOW",self._close_map_group_popup)
        popup.bind("<Escape>",self._map_clear_selection)
        popup.focus_set()

    def _cancel_map_single_click(self):
        # Variable(s): `after_id` (after id); named state retained for the surrounding calculation or subsequent calls.
        """Handle cancel map single click."""
        after_id=getattr(self,"_map_single_click_after_id",None)
        self._map_single_click_after_id=None
        self._map_single_click_marker=None
        if after_id is not None:
            try: self.root.after_cancel(after_id)
            except tk.TclError: _ignored("intentional best-effort fallback")

    def _perform_map_marker_single_click(self,marker,event_x_root=0,event_y_root=0):
        """Handle perform map marker single click."""
        self._map_single_click_after_id=None
        self._map_single_click_marker=None
        if marker.is_group:
            if self.map_selected_location in marker.member_names:
                self._map_clear_selection()
                return
            # /**
            #  * Class: E
            #  * Purpose: Encapsulate the E responsibilities and state used by this module.
            #  * @state: Instance attributes hold the durable state needed by this responsibility.
            #  */
            class E: _ignored("intentional best-effort fallback")
            # Variable(s): `e` (e); named state retained for the surrounding calculation or subsequent calls.
            e=E(); e.x_root=event_x_root; e.y_root=event_y_root
            self._show_map_group_popup(e,marker)
            return
        if self.map_selected_location == marker.location_name:
            self._map_clear_selection()
        else:
            self._select_map_location(marker.location_name)

    def _map_marker_click(self,event,marker):
        # The second release of a Tk double-click arrives after <Double-Button-1>.
        # Suppress exactly that release so it cannot schedule a fresh single-click.
        """Handle map marker click."""
        if self._map_ignore_next_release:
            self._map_ignore_next_release=False
            return "break"
        # Defer the single-click action briefly so a following double-click can
        # cancel it. This keeps selection and Path Explorer navigation separate.
        if self.map_drag_start:
            # Variable(s): `sx` (sx), `sy` (sy), `moved` (moved); named state retained for the surrounding calculation or subsequent calls.
            sx,sy,moved=self.map_drag_start
            if moved or abs(event.x-sx)>4 or abs(event.y-sy)>4: return "break"
        self._cancel_map_single_click()
        self._map_single_click_marker=marker
        self._map_single_click_after_id=self.root.after(230,lambda m=marker,x=event.x_root,y=event.y_root:self._perform_map_marker_single_click(m,x,y))
        return "break"

    def _map_marker_double_click(self,event,marker):
        """Double-click is navigation only; it never runs the pending single-click."""
        self._cancel_map_single_click()
        self._map_ignore_next_release=True
        if marker.is_group:
            self._show_map_group_popup(event,marker)
        else:
            self._select_map_location(marker.location_name)
            self.open_path(marker.location_name)
        return "break"

    def _map_empty_click(self,event=None):
        # Marker tag bindings return break before this widget binding. If there is
        # no current marker, a plain map click is an explicit deselection action.
        # Variable(s): `current` (current); named state retained for the surrounding calculation or subsequent calls.
        """Handle map empty click."""
        current=self.map_canvas.find_withtag("current") if hasattr(self,"map_canvas") else ()
        if current:
            # Variable(s): `tags` (tags); named state retained for the surrounding calculation or subsequent calls.
            tags=self.map_canvas.gettags(current[0])
            if "marker" in tags:
                return
        self._map_clear_selection()

    def _map_clear_selection(self,event=None):
        """Handle map clear selection."""
        if event is not None and getattr(self,"current_page",None) != "Map" and getattr(self,"_map_group_popup",None) is None:
            return None
        self._cancel_map_single_click()
        self._hide_map_tooltip()
        self._close_map_group_popup()
        self.map_selected_location=""
        if hasattr(self,"map_canvas"): self._refresh_map_markers()
        if hasattr(self,"map_hover"):
            self.map_hover.set("Single-click selects • Double-click opens Path Explorer • Right-click for actions • Esc / empty-map click clears selection")
        return "break" if event is not None else None

    def _show_map_location_in_checks(self,name):
        """Jump from a map marker to the matching row on the Checks page."""
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        name=(name or "").strip()
        if not name:return
        self.map_selected_location=name
        self.check_mode.set("All")
        if hasattr(self,"check_group"):self.check_group.set("None")
        self.check_search.set(name)
        self._refresh_checks()
        self.show_page("Checks")
        # Loop variable(s): `item` (item); each iteration represents the next value from the iterable below.
        pending=list(self.check_tree.get_children())
        while pending:
            item=pending.pop(0)
            pending.extend(self.check_tree.get_children(item))
            # Variable(s): `vals` (vals); named state retained for the surrounding calculation or subsequent calls.
            vals=self.check_tree.item(item,"values")
            if vals and vals[0]==name:
                self.check_tree.selection_set(item); self.check_tree.focus(item); self.check_tree.see(item)
                break

    def _ignored_scope_key(self, snapshot=None):
        """Return a stable per-server/slot/game key for persistent ignored locations."""
        snap = snapshot or self.snapshot
        identity=getattr(snap,"seed_identity",{})
        if identity:return "seed:"+identity['id'] if identity.get('complete') else ""
        server = str(getattr(snap, "server", "") or self._connection_server_value() if hasattr(self, "server_host_var") else self.initial_server).strip().lower()
        slot = str(getattr(snap, "slot_name", "") or (self.name_var.get().strip() if hasattr(self, "name_var") else self.initial_name)).strip().lower()
        game = str(getattr(snap, "game", "") or "").strip().lower()
        return "|".join((server, slot, game)) if (server or slot or game) else ""

    def _persist_ignored_location(self, name, ignored):
        """Store one ignored-location override for the current AP identity."""
        scope = self._ignored_scope_key()
        name = str(name or "").strip()
        if not scope or not name:
            return
        names = {str(x) for x in self.ignored_locations_by_scope.get(scope, []) if str(x).strip()}
        if ignored:
            names.add(name)
        else:
            names.discard(name)
        if names:
            self.ignored_locations_by_scope[scope] = sorted(names)
        else:
            self.ignored_locations_by_scope.pop(scope, None)
        self._save_settings()

    def _restore_ignored_locations_for_snapshot(self, snap):
        """Apply persisted ignores to a live snapshot and synchronize the native runtime once."""
        scope = self._ignored_scope_key(snap)
        if not scope:
            return
        names = {str(x) for x in self.ignored_locations_by_scope.get(scope, []) if str(x).strip()}
        if names:
            for loc in getattr(snap, "locations", []) or []:
                if loc.name in names and loc.status != "checked":
                    loc.ignored = True
                    loc.status = "ignored"
        if scope != self._ignored_sync_scope:
            self._ignored_sync_scope = scope
            self.runtime_client.set_ignored_locations(sorted(names))
            if names:
                self._append_log(f"Restored {len(names)} persisted ignored location(s) for this server/slot/game.")

    def _set_location_ignored(self, name, ignored=True):
        """Apply an ignore action to the UI immediately, then send it to the runtime.

        Runtime actions are asynchronous.  Without this optimistic update a location can
        remain painted as Reachable until the next tracker snapshot arrives, which
        makes the Ignored legend filter appear to be broken.
        """
        # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
        loc=next((x for x in self.snapshot.locations if x.name==name),None)
        if loc is not None:
            if ignored:
                # Preserve the underlying logic status so Unignore can restore it
                # immediately before the runtime's next authoritative snapshot arrives.
                setattr(loc, "_pre_ignore_status", loc.status if loc.status != "ignored" else "unknown")
                loc.ignored=True
                loc.status="ignored"
                self._map_canonical_marker_state[name]="ignored"
            else:
                loc.ignored=False
                # Variable(s): `restored` (restored); named state retained for the surrounding calculation or subsequent calls.
                restored=str(getattr(loc, "_pre_ignore_status", "") or "")
                if restored and restored != "ignored":
                    loc.status=restored
                else:
                    # We no longer claim it is ignored; the native runtime's next snapshot will
                    # replace this conservative temporary state with reachability.
                    loc.status="unknown"
                self._map_canonical_marker_state[name]=loc.status
        self._persist_ignored_location(name, ignored)
        if ignored:
            self.runtime_client.ignore_location(name)
        else:
            self.runtime_client.unignore_location(name)
        self._refresh_checks()
        self._refresh_ignored()
        if hasattr(self,"map_canvas"):
            self._refresh_map_markers(force_rebuild=True)
        self._refresh_map_group_popup()

    def _map_marker_context_menu(self,event,name):
        """Show navigation and tracker actions for a map marker."""
        self._select_map_location(name)
        # Variable(s): `loc` (loc); named state retained for the surrounding calculation or subsequent calls.
        loc=next((x for x in self.snapshot.locations if x.name==name),None)
        # Variable(s): `menu` (menu); named state retained for the surrounding calculation or subsequent calls.
        menu=tk.Menu(self.root,tearoff=False)
        menu.add_command(label="Open in Path Explorer",command=lambda:self.open_path(name))
        menu.add_command(label="Why reachable?",command=lambda:self._show_logic_explanation(name,False))
        menu.add_command(label="What's missing?",command=lambda:self._show_logic_explanation(name,True))
        menu.add_command(label="Copy location",command=lambda:self.root.clipboard_append(name))
        menu.add_command(label="Personal note…",command=lambda:self._personal_note(name))
        menu.add_command(label="Show in Checks",command=lambda:self._show_map_location_in_checks(name))
        if loc is not None:
            menu.add_separator()
            if loc.ignored:
                menu.add_command(label="Unignore Location",command=lambda:self._set_location_ignored(name,False))
            else:
                menu.add_command(label="Ignore Location",command=lambda:self._set_location_ignored(name,True))
        try:
            menu.tk_popup(event.x_root,event.y_root)
        finally:
            menu.grab_release()
        return "break"

    def _pulse_player_marker(self):
        """Handle pulse player marker."""
        if self._closing:return
        self._player_pulse_on=not getattr(self,"_player_pulse_on",False)
        try:
            if hasattr(self,"map_canvas"): self.map_canvas.itemconfigure("player_position",width=4 if self._player_pulse_on else 2)
        except tk.TclError: _ignored("intentional best-effort fallback")
        self.root.after(650,self._pulse_player_marker)

