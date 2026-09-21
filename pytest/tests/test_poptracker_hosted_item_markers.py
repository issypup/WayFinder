from wayfinder.maps.interpretation import iter_marker_records

def test_hosted_item_sections_are_preserved_as_tracker_only_checks():
    data=[{"name":"Slime Citadel","children":[{"name":"Slurp Stone","map_locations":[{"map":"FF","x":2130,"y":1704}],"sections":[{"name":"Summoning Stone","hosted_item":"SS3","item_count":1}]}]}]
    records=list(iter_marker_records(data, {}))
    assert len(records)==1
    assert records[0]["source_path"]=="Slime Citadel/Slurp Stone"
    assert records[0]["section_tracker_only"]==(True,)
    assert records[0]["location_ids"]==((),)
