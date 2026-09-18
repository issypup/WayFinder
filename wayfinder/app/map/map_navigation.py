"""Provide map navigation support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

from .map_shared import *

class MapNavigationMixin:
    """Map subsystem responsibilities extracted from MapPageMixin."""
    def _map_pan_start(self,event):
        """Handle map pan start."""
        self.map_drag_start=[event.x,event.y,False]
        self.map_canvas.configure(cursor="fleur")
        self.map_canvas.scan_mark(event.x,event.y)

    def _map_pan_move(self,event):
        """Handle map pan move."""
        if self.map_drag_start:
            if abs(event.x-self.map_drag_start[0])>3 or abs(event.y-self.map_drag_start[1])>3:
                self.map_drag_start[2]=True
        self.map_canvas.scan_dragto(event.x,event.y,gain=1)
        self._update_minimap_viewport()

    def _map_pan_end(self,event):
        """Handle map pan end."""
        self.map_canvas.configure(cursor="arrow")
        self.map_drag_start=None
        self._update_minimap_viewport()
        self._remember_map_view()
        return "break"

    def _change_map_zoom(self,direction,event=None):
        # Variable(s): `levels` (levels); named state retained for the surrounding calculation or subsequent calls.
        """Handle change map zoom."""
        levels=ZOOM_CACHE_LEVELS; current=int(self.map_zoom.get())
        # Variable(s): `i` (index); named state retained for the surrounding calculation or subsequent calls.
        try: i=levels.index(current)
        # Variable(s): `i` (index); named state retained for the surrounding calculation or subsequent calls.
        except ValueError: i=min(range(len(levels)), key=lambda n:abs(levels[n]-current))
        # Variable(s): `new` (new); named state retained for the surrounding calculation or subsequent calls.
        new=levels[max(0,min(len(levels)-1,i+direction))]
        if new!=current:
            # Store the point beneath the cursor in unscaled map coordinates.
            # The async renderer reapplies the viewport after the new image lands.
            if event is not None and self.map_photo is not None:
                # Variable(s): `factor` (factor); named state retained for the surrounding calculation or subsequent calls.
                factor=max(0.01,current/100.0)
                self._map_zoom_anchor=(self.map_canvas.canvasx(event.x)/factor, self.map_canvas.canvasy(event.y)/factor, event.x, event.y, new)
            else:
                # Variable(s): `vw` (vw); named state retained for the surrounding calculation or subsequent calls.
                vw=max(1,self.map_canvas.winfo_width()); vh=max(1,self.map_canvas.winfo_height()); factor=max(0.01,current/100.0)
                self._map_zoom_anchor=(self.map_canvas.canvasx(vw/2)/factor, self.map_canvas.canvasy(vh/2)/factor, vw/2, vh/2, new)
            self.map_zoom.set(new)
            self._remember_map_view()
            self._request_map_render(preserve_view=True, delay=45 if event is not None else 80)

    def _map_ctrl_mousewheel(self,event):
        """Handle map ctrl mousewheel."""
        self._change_map_zoom(1 if event.delta>0 else -1,event); return "break"

    def _map_mousewheel(self,event):
        # Dedicated-map behaviour: wheel zooms around the cursor. Shift+wheel pans horizontally.
        """Handle map mousewheel."""
        if event.state & 0x0001:
            self.map_canvas.xview_scroll(int(-1*(event.delta/120)),"units")
            return "break"
        self._change_map_zoom(1 if event.delta>0 else -1,event)
        return "break"

    def _push_map_history(self):
        """Handle push map history."""
        if not hasattr(self,"map_selector_var"): return
        title=self.map_selector_var.get().strip()
        if not title:return
        state=(title,self.map_selected_location,int(self.map_zoom.get()),self.map_canvas.xview()[0] if hasattr(self,"map_canvas") else 0.0,self.map_canvas.yview()[0] if hasattr(self,"map_canvas") else 0.0)
        if self.map_navigation_index>=0 and self.map_navigation_history[self.map_navigation_index][0]==title:return
        self.map_navigation_history=self.map_navigation_history[:self.map_navigation_index+1]; self.map_navigation_history.append(state); self.map_navigation_index=len(self.map_navigation_history)-1

    def _restore_map_history_state(self,state):
        """Handle restore map history state."""
        title,selection,zoom,x,y=state; self.map_selector_var.set(title); self.map_selected_location=selection; self.map_zoom.set(zoom); self._request_map_render(preserve_view=False,delay=20); self.root.after(120,lambda:(self.map_canvas.xview_moveto(x),self.map_canvas.yview_moveto(y),self._refresh_map_markers()))

    def _map_history_back(self):
        """Handle map history back."""
        if self.map_navigation_index>0:self.map_navigation_index-=1; self._restore_map_history_state(self.map_navigation_history[self.map_navigation_index])

    def _map_history_forward(self):
        """Handle map history forward."""
        if self.map_navigation_index+1<len(self.map_navigation_history):self.map_navigation_index+=1; self._restore_map_history_state(self.map_navigation_history[self.map_navigation_index])

    def _focus_location_on_map(self,name,switch_to_map=False):
        # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
        """Handle focus location on map."""
        name=(name or '').strip(); pack=self.active_map_pack
        if not name or not pack: return False
        # Variable(s): `markers` (markers); named state retained for the surrounding calculation or subsequent calls.
        markers=pack.markers_by_location.get(name,())
        if not markers: return False
        # Variable(s): `marker` (marker); named state retained for the surrounding calculation or subsequent calls.
        marker=markers[0]
        # Variable(s): `target_md` (target md); named state retained for the surrounding calculation or subsequent calls.
        target_md=next((md for md in pack.maps if md.name==marker.map_name),None)
        if target_md is not None and self.map_selector_var.get()!=target_md.title:
            self.map_selector_var.set(target_md.title); self._remember_current_map(); self._request_map_render(preserve_view=False,delay=20)
        self._select_map_location(name)
        if switch_to_map: self.show_page('Map')
        # /**
        #  * Function: center
        #  * Purpose: Perform the center operation while keeping the surrounding subsystem state consistent.
        #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
        #  */
        def center():
            # Variable(s): `md` (metadata); named state retained for the surrounding calculation or subsequent calls.
            """Handle center."""
            md=self._current_map_def()
            if not md or self.map_photo is None:return
            # Variable(s): `factor` (factor); named state retained for the surrounding calculation or subsequent calls.
            factor=int(self.map_zoom.get())/100.0; w=max(1,self.map_photo.width()); h=max(1,self.map_photo.height())
            # Variable(s): `vw` (vw); named state retained for the surrounding calculation or subsequent calls.
            vw=max(1,self.map_canvas.winfo_width()); vh=max(1,self.map_canvas.winfo_height())
            self.map_canvas.xview_moveto(max(0,min(1,(marker.x*factor-vw/2)/w)))
            self.map_canvas.yview_moveto(max(0,min(1,(marker.y*factor-vh/2)/h)))
            self._update_minimap_viewport(); self._refresh_map_markers()
        self.root.after(120,center)
        return True

    def _minimap_option_changed(self):
        """Handle minimap option changed."""
        if hasattr(self,'minimap_canvas'):
            if self.map_show_minimap.get(): self.minimap_canvas.place(relx=1.0,rely=0.0,x=-10,y=10,anchor='ne'); self._refresh_minimap()
            else: self.minimap_canvas.place_forget()

    def _refresh_minimap(self):
        """Render the minimap independently from the main-map render generation.

        The minimap owns its own image key/photo and projects the same canonical
        marker state used by the main map.
        """
        if not hasattr(self,'minimap_canvas') or not self.map_show_minimap.get():
            return
        # Variable(s): `pack` (pack); named state retained for the surrounding calculation or subsequent calls.
        pack=self.active_map_pack; md=self._current_map_def()
        if not pack or not md:
            return
        try:
            from PIL import Image,ImageTk
            Image.MAX_IMAGE_PIXELS = None
            # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
            key=asset_key(pack,md.image,int(self.map_zoom.get()))
            # Variable(s): `c` (c); named state retained for the surrounding calculation or subsequent calls.
            c=self.minimap_canvas
            if self._minimap_key != key or self._minimap_photo is None:
                preview=getattr(self,"_map_preview",None)
                if preview is None or preview[0] != key:
                    return
                im,(base_w,base_h)=preview[1]
                self._minimap_photo=ImageTk.PhotoImage(im)
                self._minimap_key=key
                self._minimap_scale=(im.width/max(1.0,base_w), im.height/max(1.0,base_h))
                c.delete('all')
                c.configure(width=im.width+6,height=im.height+6)
                c.create_image(3,3,anchor='nw',image=self._minimap_photo,tags=('mini_image',))
            c.delete('mini_marker')
            # Variable(s): `sx` (sx), `sy` (sy); named state retained for the surrounding calculation or subsequent calls.
            sx,sy=getattr(self,'_minimap_scale',(1.0,1.0))
            # Variable(s): `palette` (palette); named state retained for the surrounding calculation or subsequent calls.
            palette={k:v["color"] for k,v in STATUS_VISUALS.items()}
            # Variable(s): `canonical` (canonical); named state retained for the surrounding calculation or subsequent calls.
            canonical=self._map_canonical_marker_state
            # Loop variable(s): `marker` (marker); each iteration represents the next value from the iterable below.
            for marker in pack.markers_by_map.get(md.name,()):
                # Variable(s): `states` (states); named state retained for the surrounding calculation or subsequent calls.
                states=[canonical.get(name,"unknown") for name in marker.member_names]
                # Variable(s): `priority` (priority); named state retained for the surrounding calculation or subsequent calls.
                priority=("reachable","glitched","out_of_logic","non_progression","unknown","ignored","checked")
                # Variable(s): `status` (status); named state retained for the surrounding calculation or subsequent calls.
                status=next((s for s in priority if s in states),"unknown")
                if status in self.map_status_visible and not self.map_status_visible[status].get():
                    continue
                # Variable(s): `x` (horizontal x-coordinate); named state retained for the surrounding calculation or subsequent calls.
                x=3+marker.x*sx; y=3+marker.y*sy
                c.create_oval(x-1.5,y-1.5,x+1.5,y+1.5,fill=palette.get(status,palette["unknown"]),outline="",tags=('mini_marker',))
            self._update_minimap_viewport()
        except Exception:
            try:
                self.minimap_canvas.delete('all')
                self.minimap_canvas.create_text(95,70,text='Minimap unavailable',fill='white')
            except Exception:
                _ignored("intentional best-effort fallback")

    def _update_minimap_viewport(self):
        """Handle update minimap viewport."""
        if not hasattr(self,'minimap_canvas') or not self.map_show_minimap.get() or self.map_photo is None:return
        try:
            # Variable(s): `c` (c); named state retained for the surrounding calculation or subsequent calls.
            c=self.minimap_canvas; bbox=c.bbox('mini_image')
            if not bbox:return
            # Variable(s): `x0` (starting x-coordinate), `x1` (first x-coordinate); named state retained for the surrounding calculation or subsequent calls.
            x0,x1=self.map_canvas.xview(); y0,y1=self.map_canvas.yview(); l,t,r,b=bbox; w=r-l; h=b-t
            c.delete('viewport'); c.create_rectangle(l+x0*w,t+y0*h,l+x1*w,t+y1*h,outline='#ffffff',width=2,tags=('viewport',))
        except Exception: _ignored("intentional best-effort fallback")

    def _minimap_jump(self,event):
        """Handle minimap jump."""
        try:
            # Variable(s): `bbox` (bbox); named state retained for the surrounding calculation or subsequent calls.
            bbox=self.minimap_canvas.bbox('mini_image')
            if not bbox:return 'break'
            # Variable(s): `l` (l), `t` (t), `r` (r), `b` (b); named state retained for the surrounding calculation or subsequent calls.
            l,t,r,b=bbox; px=max(0,min(1,(event.x-l)/max(1,r-l))); py=max(0,min(1,(event.y-t)/max(1,b-t)))
            # Variable(s): `xspan` (xspan); named state retained for the surrounding calculation or subsequent calls.
            xspan=self.map_canvas.xview()[1]-self.map_canvas.xview()[0]; yspan=self.map_canvas.yview()[1]-self.map_canvas.yview()[0]
            self.map_canvas.xview_moveto(max(0,min(1-xspan,px-xspan/2))); self.map_canvas.yview_moveto(max(0,min(1-yspan,py-yspan/2))); self._update_minimap_viewport()
        except Exception: _ignored("intentional best-effort fallback")
        return 'break'

