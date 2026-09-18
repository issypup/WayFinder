"""Conservative map coverage reports and evidence-based check filters."""
from collections import defaultdict

def check_evidence(snapshot):
    """Return check evidence."""
    progression=set(); remote=set()
    hints=[h for h in snapshot.hints if isinstance(h,dict)]
    missing={}
    for name,detail in snapshot.rule_details.items():
        missing[name]={str(r.get('name','')) for r in detail.get('missing',[]) if isinstance(r,dict) and r.get('kind') in ('item','item_count')}
    for hint in hints:
        item=str(hint.get('item') or hint.get('item_name') or '')
        location=str(hint.get('location') or hint.get('location_name') or '')
        finder=str(hint.get('finding_player') or hint.get('finder') or '')
        receiver=str(hint.get('receiving_player') or hint.get('receiver') or '')
        try: flags=int(hint.get('item_flags',hint.get('flags',0)) or 0)
        except (ValueError,TypeError):flags=0
        is_progression=bool(hint.get('progression')) or bool(flags&1)
        if is_progression and (not finder or finder==snapshot.slot_name):progression.add(location)
        if finder and finder!=snapshot.slot_name and (not receiver or receiver==snapshot.slot_name):
            remote.update(name for name,items in missing.items() if item in items)
    return progression,remote

def map_intelligence(snapshot,pack,resolve):
    """Handle map intelligence."""
    live={loc.name for loc in snapshot.locations}; covered=set(); unknown=[]; entrance_unknown=[]; by_location=defaultdict(set)
    entrance_names={str(row.get('name','')) for row in snapshot.entrance_details if isinstance(row,dict)}
    unknown_live=[loc.name+(': '+loc.unknown_reason if getattr(loc,'unknown_reason','') else '') for loc in snapshot.locations if loc.status=='unknown']
    if pack is None:return dict(missing_markers=sorted(live),unknown_locations=[],unknown_live_locations=unknown_live,unknown_entrances=[],maps={},available=False)
    map_names={m.name for m in pack.maps}
    for marker in pack.markers:
        if marker.is_entrance_marker:
            candidates={marker.location_name,*marker.member_names}
            if not candidates & entrance_names:entrance_unknown.append(marker.location_name)
            continue
        for index,name in enumerate(marker.member_names):
            resolved=resolve(marker,index)
            canonical=getattr(resolved,"name",resolved)
            if canonical in live and marker.map_name in map_names:
                covered.add(canonical);by_location[canonical].add(next((m.title for m in pack.maps if m.name==marker.map_name),marker.map_name))
            else:unknown.append(name)
    entrance_unknown.extend(str(row.get('name','Unnamed entrance')) for row in snapshot.entrance_details if isinstance(row,dict) and (row.get('unknown') or row.get('status')=='unknown' or row.get('available') is False))
    return dict(missing_markers=sorted(live-covered),unknown_live_locations=unknown_live,unknown_locations=sorted(set(unknown)),unknown_entrances=sorted(set(entrance_unknown)),maps={key:sorted(value) for key,value in by_location.items()},available=True)
