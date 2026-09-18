"""Provide map routes support."""
from __future__ import annotations

from wayfinder.utils.ignored import ignored as _ignored

from .map_shared import *

class MapRoutesMixin:
    """Map subsystem responsibilities extracted from MapPageMixin."""
    def _route_overlay_points_for_map(self, md):
        """Resolve the current logical path into drawable points on one map.

        Path Explorer describes APWorld regions/entrances, while legacy map packs
        normally provide coordinates only for locations.  Exact location matches
        are therefore supplemented with a representative centroid for each route
        region using the snapshot's location->region relationship.  The result is
        deliberately an *approximate logical route*, not claimed physical geometry.
        """
        pack=self.active_map_pack; result=self.current_path
        if pack is None or md is None or result is None or not result.found:
            return []
        factor=int(self.map_zoom.get())/100.0
        location_state={x.name:x for x in self.snapshot.locations}
        region_points={}
        for marker in pack.markers_by_map.get(md.name,()):
            regions=set()
            for member_name in marker.member_names:
                loc=location_state.get(member_name)
                region=str(getattr(loc,"region","") or "").strip() if loc is not None else ""
                if region: regions.add(region.casefold())
            for region in regions:
                region_points.setdefault(region,[]).append((marker.x*factor,marker.y*factor))

        def centroid(region_name):
            """Handle centroid."""
            pts=region_points.get(str(region_name or "").strip().casefold(),())
            if not pts:return None
            return (sum(x for x,_ in pts)/len(pts),sum(y for _,y in pts)/len(pts))

        ordered=[]
        def add_point(point,label,kind):
            """Handle add point."""
            if point is None:return
            # Consecutive structural steps often resolve to the same region
            # centroid; collapse them so the line remains legible.
            if ordered and abs(ordered[-1][0]-point[0])<1.0 and abs(ordered[-1][1]-point[1])<1.0:
                ordered[-1]=(point[0],point[1],label or ordered[-1][2],kind)
                return
            ordered.append((point[0],point[1],label,kind))

        for step in result.steps:
            # Prefer a real check coordinate whenever the step title is a map
            # location.  Entrance/region-only steps fall back to region centroids.
            exact=[m for m in pack.markers_by_location.get(step.title,()) if m.map_name==md.name]
            if exact:
                add_point((exact[0].x*factor,exact[0].y*factor),step.title,"location")
                continue
            add_point(centroid(step.source_region),step.source_region,"region")
            add_point(centroid(step.target_region),step.target_region,"region")

        # Older/opaque path producers may omit a final location step. Always try
        # the PathResult target so Route overlay still gives visible feedback.
        target_markers=[m for m in pack.markers_by_location.get(result.target,()) if m.map_name==md.name]
        if target_markers:
            target=target_markers[0]
            add_point((target.x*factor,target.y*factor),result.target,"target")
        return ordered

    def _draw_route_overlay_on_canvas(self, canvas, md):
        """Handle draw route overlay on canvas."""
        canvas.delete("route_overlay")
        if not bool(getattr(self, "map_route_overlay", None) and self.map_route_overlay.get()):
            return
        points = self._route_overlay_points_for_map(md)
        if len(points) < 2:
            return
        coords = [coord for x, y, _label, _kind in points for coord in (x, y)]
        canvas.create_line(*coords, width=4, arrow="last", smooth=True, tags=("route_overlay",))
        for index, (x, y, label, kind) in enumerate(points, start=1):
            radius = 6 if kind in {"location", "target"} else 4
            canvas.create_oval(x-radius, y-radius, x+radius, y+radius, width=2, tags=("route_overlay",))
            if label:
                canvas.create_text(x+9, y-9, text=str(index), anchor="sw", tags=("route_overlay",))
        canvas.tag_raise("route_overlay")

    def _draw_route_overlay(self):
        """Handle draw route overlay."""
        canvas = getattr(self, "map_canvas", None)
        pack = getattr(self, "active_map_pack", None)
        if canvas is None or pack is None:
            return
        map_name = str(getattr(self, "current_map_name", "") or "")
        md = next((item for item in getattr(pack, "maps", ()) if item.name == map_name), None)
        if md is not None:
            self._draw_route_overlay_on_canvas(canvas, md)

