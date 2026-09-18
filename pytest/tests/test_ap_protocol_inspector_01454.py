"""Provide test ap protocol inspector 01454 support."""
import asyncio
import json
from types import SimpleNamespace

import pytest
from wayfinder.connection.ap_inspector import APInspector, browse, preview
from wayfinder.runtime.ap_protocol import install_packet_observer
from wayfinder.runtime.server import NativeRuntime


def connected():
    """Handle connected."""
    inspector=APInspector()
    inspector.record('IN','RoomInfo',{'seed_name':'A'})
    inspector.record('IN','Connected',{'checked_locations':[1], 'missing_locations':[2,3]})
    return inspector


def test_packet_types_counts_and_latest_survive_ring_eviction():
    """Handle test packet types counts and latest survive ring eviction."""
    inspector=connected()
    for _ in range(130):inspector.record('IN','RoomUpdate',{})
    data=inspector.summary()
    assert len(data['packets'])==100
    assert any(row['command']=='Connected' for row in data['latest'])
    assert next(r['count'] for r in data['counts'] if r['command']=='RoomUpdate')==130


def test_new_room_resets_previous_seed_state():
    """Handle test new room resets previous seed state."""
    inspector=connected();epoch=inspector.epoch
    inspector.record('IN','ReceivedItems',{'index':0,'items':[[1,2,3,0]]})
    inspector.record('IN','RoomInfo',{'seed_name':'B'})
    assert inspector.epoch!=epoch and not inspector.checked and inspector.expected_index is None
    assert len(inspector.history)==1 and not inspector.authoritative


def test_room_updates_are_deltas_not_replacements():
    """Handle test room updates are deltas not replacements."""
    inspector=connected()
    inspector.record('IN','RoomUpdate',{'checked_locations':[2]})
    inspector.record('IN','RoomUpdate',{'checked_locations':[]})
    assert inspector.checked=={1,2}


def test_received_items_gap_duplicate_and_full_reset():
    """Handle test received items gap duplicate and full reset."""
    inspector=connected()
    inspector.record('IN','ReceivedItems',{'index':0,'items':[[1,1,1,0]]})
    inspector.record('IN','ReceivedItems',{'index':3,'items':[[2,2,2,0]]})
    assert 'gap' in inspector.item_state and inspector.expected_index==1
    inspector.record('IN','ReceivedItems',{'index':0,'items':[[1,1,1,0],[2,2,2,0]]})
    assert inspector.expected_index==2 and inspector.item_state.startswith('In sequence')
    inspector.record('IN','ReceivedItems',{'index':1,'items':[[2,2,2,0]]})
    assert 'duplicate' in inspector.item_state and inspector.expected_index==2
    inspector.record('IN','ReceivedItems',{'index':2,'items':[[3,3,3,0]]})
    assert inspector.expected_index==3


@pytest.mark.parametrize('index',[-1,True,'2',None])
def test_malformed_item_index_is_reported(index):
    """Handle test malformed item index is reported."""
    inspector=connected();inspector.record('IN','ReceivedItems',{'index':index,'items':[]})
    assert inspector.item_state=='Invalid packet'


def test_missing_initial_items_not_hidden_by_old_core_inventory():
    """Handle test missing initial items not hidden by old core inventory."""
    inspector=connected()
    inspector.record('IN','ReceivedItems',{'index':10,'items':[]},before_count=10)
    assert 'gap' in inspector.item_state


def test_numeric_check_discrepancies_and_snapshot_lag():
    """Handle test numeric check discrepancies and snapshot lag."""
    inspector=connected()
    snapshot={'locations':[{'address':2,'status':'checked','name':'Check'}]}
    comparison=inspector.comparison(snapshot,inspector.check_revision,inspector.epoch)
    assert not comparison['pending'] and comparison['total_discrepancies']==2
    assert {r['id'] for r in comparison['discrepancies']}=={1,2}
    inspector.record('IN','RoomUpdate',{'checked_locations':[2]})
    assert inspector.comparison(snapshot,inspector.check_revision-1,inspector.epoch)['pending']


def test_latency_requires_matching_reply_and_empty_inventory_is_not_false_success(monkeypatch):
    """Handle test latency requires matching reply and empty inventory is not false success."""
    import wayfinder.connection.ap_inspector as module
    clock=[10.0];monkeypatch.setattr(module.time,'monotonic',lambda:clock[0])
    inspector=connected();nonce=inspector.probe()
    inspector.resync=dict(state='Waiting',started=clock[0],request=nonce,items='Waiting')
    clock[0]=10.025
    inspector.record('IN','Retrieved',{'keys':{},'wf_inspector_request':'wrong'})
    assert not inspector.latencies
    inspector.record('IN','Retrieved',{'keys':{},'wf_inspector_request':nonce})
    assert inspector.latencies[-1]==25
    clock[0]=30
    assert inspector.summary()['resync']['state'].startswith('Partial')


def test_preview_is_bounded_redacted_and_handles_recursive_values():
    """Handle test preview is bounded redacted and handles recursive values."""
    value={'password':'hidden','nested':{'api_token':'private'},'payload':['🧭'*3000]*1000}
    result=preview(value)
    assert 'hidden' not in result and 'private' not in result
    assert len(result.encode())<4300
    recursive={};recursive['self']=recursive
    assert 'preview limit' in preview(recursive)


def test_browser_paginates_and_preserves_types_and_protects_secret_paths():
    """Handle test browser paginates and preserves types and protects secret paths."""
    value={'options':list(range(250)),'auth_token':{'value':'secret'}}
    page=browse(value,['options'],100)
    assert len(page['rows'])==100 and page['next']==200
    assert page['rows'][0]['path']==['options',100]
    assert page['rows'][0]['type']=='int'
    assert 'secret' not in json.dumps(browse(value,['auth_token']))
    assert 'secret' not in json.dumps(browse(value,['auth_token','value']))


def test_observer_captures_before_core_processing_and_is_idempotent():
    """Handle test observer captures before core processing and is idempotent."""
    inspector=connected();seen=[]
    runtime=SimpleNamespace(ap_inspector=inspector,after_ap_packet=lambda args:seen.append('after'))
    async def process(ctx,args):
        """Handle process."""
        seen.append(inspector.expected_index);ctx.items_received.extend(args['items'])
    module=SimpleNamespace(process_server_cmd=process)
    install_packet_observer(module);wrapper=module.process_server_cmd;install_packet_observer(module)
    assert wrapper is module.process_server_cmd
    ctx=SimpleNamespace(_wayfinder_runtime=runtime,items_received=[])
    asyncio.run(module.process_server_cmd(ctx,{'cmd':'ReceivedItems','index':0,'items':[[1,1,1,0]]}))
    assert seen==[1,'after'] and len(ctx.items_received)==1


def runtime_fixture():
    """Handle runtime fixture."""
    runtime=NativeRuntime(0,'.');runtime.connection_id='connection'
    runtime.ap_inspector=connected();sent=[];statuses=[]
    async def send_msgs(packets):sent.extend(packets)
    runtime.ctx=SimpleNamespace(slot=1,team=0,game='Demo',auth='Player',server=object(),slot_data={'option':True},
                                checked_locations={99},missing_locations=set(),stored_data={},stored_data_notification_keys=set(),send_msgs=send_msgs)
    runtime.send_status=lambda name,value:statuses.append((name,value))
    runtime.publish=lambda *a:None
    return runtime,sent,statuses


def test_resync_only_sends_sync_and_get_and_retains_connection_and_world():
    """Handle test resync only sends sync and get and retains connection and world."""
    runtime,sent,statuses=runtime_fixture();built=object();runtime.built=built;ctx=runtime.ctx
    try:
        asyncio.run(runtime.inspector_request({'action':'resync','id':1}))
        assert [p['cmd'] for p in sent]==['Sync','Get']
        assert runtime.ctx is ctx and runtime.built is built and runtime.connection_id=='connection'
        assert ctx.checked_locations=={1} and ctx.missing_locations=={2,3}
        assert '_read_slot_data_1' in sent[-1]['keys']
        assert statuses[-1][0]=='ap_inspector' and statuses[-1][1]['resync']['state']=='Waiting'
    finally:runtime.jobs.close()


def test_resync_does_not_apply_changed_slot_data_under_old_seed_identity():
    """Handle test resync does not apply changed slot data under old seed identity."""
    runtime,sent,statuses=runtime_fixture()
    try:
        asyncio.run(runtime.inspector_request({'action':'resync','id':1}))
        nonce=sent[-1]['wf_inspector_request']
        runtime.after_ap_packet({'cmd':'Retrieved','wf_inspector_request':nonce,'keys':{'_read_slot_data_1':{'option':False}}})
        assert runtime.ctx.slot_data=={'option':True}
        assert 'Changed' in runtime.ap_inspector.resync['slot_data']
    finally:runtime.jobs.close()


def test_storage_relevance_uses_own_slot_and_world_subscriptions():
    """Handle test storage relevance uses own slot and world subscriptions."""
    runtime,_,_=runtime_fixture()
    runtime.built=SimpleNamespace(resolved_map_page_setting_key='map_1')
    runtime.ctx.stored_data={'_read_hints_0_2':['other'], 'Demo_relics':[], 'unrelated':1}
    runtime.ctx.stored_data_notification_keys={'_read_hints_0_2','current_position_1'}
    try:
        relevant=runtime.relevant_storage()
        assert {'map_1','Demo_relics','current_position_1','_read_hints_0_1'}<=set(relevant)
        assert '_read_hints_0_2' not in relevant and 'unrelated' not in relevant
    finally:runtime.jobs.close()


def test_browser_rejects_old_connection_and_unrelated_storage():
    """Handle test browser rejects old connection and unrelated storage."""
    runtime,_,statuses=runtime_fixture()
    try:
        asyncio.run(runtime.inspector_request({'action':'browse','scope':'slot_data','epoch':'old','id':1}))
        assert statuses[-1][0]=='ap_inspector_error'
        asyncio.run(runtime.inspector_request({'action':'browse','scope':'storage','key':'other','epoch':runtime.ap_inspector.epoch,'id':2}))
        assert 'not relevant' in statuses[-1][1]['message']
    finally:runtime.jobs.close()


def test_comparison_uses_displayed_gui_and_flags_old_generation():
    """Handle test comparison uses displayed gui and flags old generation."""
    runtime,_,statuses=runtime_fixture()
    runtime.last_snapshot={'snapshot_sequence':5,'locations':[{'address':1,'name':'Chest','status':'checked'}]}
    runtime._inspector_snapshot_epoch=runtime.ap_inspector.epoch
    runtime._inspector_snapshot_revision=runtime.ap_inspector.check_revision
    try:
        asyncio.run(runtime.inspector_request({'action':'summary','gui':dict(checked=[],generation=4,runtime_id=runtime.runtime_id,connection_id='connection')}))
        comparison=statuses[-1][1]['comparison']
        assert comparison['pending'] and comparison['total_discrepancies']==1
        assert comparison['target']=='Displayed GUI snapshot'
    finally:runtime.jobs.close()


def test_storage_live_previews_update_and_redact_sensitive_keys():
    """Handle test storage live previews update and redact sensitive keys."""
    runtime,_,_=runtime_fixture()
    runtime.ctx.stored_data_notification_keys={'Demo_token','current_map'}
    runtime.ctx.stored_data={'Demo_token':'private-value','current_map':1}
    try:
        rows=runtime.storage_rows()
        assert 'private-value' not in json.dumps(rows)
        assert next(r['value'] for r in rows if r['key']=='current_map')=='1'
        runtime.ctx.stored_data['current_map']=2
        assert next(r['value'] for r in runtime.storage_rows() if r['key']=='current_map')=='2'
    finally:runtime.jobs.close()


def test_server_actions_reject_stale_epoch_and_closed_socket():
    """Handle test server actions reject stale epoch and closed socket."""
    runtime,sent,statuses=runtime_fixture()
    try:
        asyncio.run(runtime.inspector_request(dict(action='resync',epoch='old')))
        assert not sent and statuses[-1][0]=='ap_inspector_error'
        runtime.ctx.server=SimpleNamespace(socket=SimpleNamespace(open=False,closed=True))
        asyncio.run(runtime.inspector_request(dict(action='resync',epoch=runtime.ap_inspector.epoch)))
        assert not sent and 'Connect' in statuses[-1][1]['message']
    finally:runtime.jobs.close()


def test_inspector_summary_stays_under_ipc_limit_with_unicode_payloads():
    """Handle test inspector summary stays under ipc limit with unicode payloads."""
    inspector=connected()
    for index in range(200):inspector.record('IN','Custom'+str(index),{'text':'🧭'*10000})
    assert len(json.dumps(inspector.summary(),ensure_ascii=False).encode())<2*1024*1024
