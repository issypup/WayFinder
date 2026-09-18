"""Provide test reliability seed intelligence support."""
import copy
import json
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import pytest
from wayfinder.connection.identity import seed_identity,validate_identity,validate_snapshot,SnapshotGate
from wayfinder.connection.protocol import decode_snapshot,encode_snapshot
from wayfinder.runtime.reliability import RuntimeJobs,HealthState,STATES
from wayfinder.runtime.server import NativeRuntime
from wayfinder.connection.runtime_client import Snapshot,LocationEntry,WayFinderRuntimeClient
from wayfinder.maps.packs import MapPack,MapDefinition,MapMarker
from wayfinder.maps.intelligence import map_intelligence,check_evidence


def context(seed='seed-A'):
    """Handle context."""
    return SimpleNamespace(server_address='HOST:38281',auth='Player',slot=1,team=0,seed_name=seed,game='Demo',slot_data={'option':2})

def packet(seq=1,connection='connection',seed='seed-A'):
    """Handle packet."""
    ctx=context(seed);identity=seed_identity(ctx,SimpleNamespace(world_version='1.0'))
    return dict(connected=True,server=ctx.server_address,slot_name=ctx.auth,game=ctx.game,team=0,seed_identity=identity,connection_id=connection,runtime_id='runtime',snapshot_sequence=seq,locations=[dict(name='Check',status='reachable')],inventory=[])


def test_identity_is_stable_and_covers_each_seed_dimension():
    """Handle test identity is stable and covers each seed dimension."""
    ctx=context();first=seed_identity(ctx,SimpleNamespace(world_version='1.0'))
    ctx.server_address='ws://host:38281/'
    assert seed_identity(ctx,SimpleNamespace(world_version='1.0'))['id']==first['id']
    for key,value in [('seed_name','new'),('slot',2),('team',1),('game','Other'),('slot_data',{'option':3}),('auth','Other'),('server_address','other:38281')]:
        changed=copy.copy(ctx);setattr(changed,key,value)
        assert seed_identity(changed,SimpleNamespace(world_version='1.0'))['id']!=first['id']
    assert seed_identity(ctx,SimpleNamespace(world_version='2.0'))['id']!=first['id']


def test_identity_digest_rejects_tampering():
    """Handle test identity digest rejects tampering."""
    identity=packet()['seed_identity'];identity['seed']='changed'
    with pytest.raises(ValueError):validate_identity(identity)


def test_snapshot_gate_order_target_connection_seed_and_commit():
    """Handle test snapshot gate order target connection seed and commit."""
    gate=SnapshotGate();gate.begin('connection','host:38281','Player');data=packet()
    with pytest.raises(ValueError):gate.check(data)
    assert gate.announce(data['seed_identity'],'connection')
    gate.check(data);gate.commit(data)
    with pytest.raises(ValueError):gate.check(data)
    gate.check(packet(2))
    assert gate.sequences['runtime']==1
    with pytest.raises(ValueError):gate.check(packet(3,'old'))
    with pytest.raises(ValueError):gate.check(packet(3,seed='other'))
    gate.begin('new','host:38281','Different')
    assert not gate.announce(data['seed_identity'],'new')

@pytest.mark.parametrize('change',[{'locations':[{'name':'X','status':'invalid'}]},{'locations':[{'name':'X','status':'reachable'},{'name':'X','status':'checked'}]},{'snapshot_sequence':-1},{'inventory':[{'name':'Item','count':'bad'}]},{'server':'different'},{'connected':'true'}])
def test_snapshot_validation_rejects_corruption(change):
    """Handle test snapshot validation rejects corruption."""
    data=packet();data.update(change)
    with pytest.raises(ValueError):validate_snapshot(data,True)


def test_compressed_snapshot_rejects_truncation():
    """Handle test compressed snapshot rejects truncation."""
    data={'locations':['x'*200000]};encoded=encode_snapshot(data)
    assert decode_snapshot(encoded)==data
    encoded['data']=encoded['data'][:-4]
    with pytest.raises((ValueError,Exception)):decode_snapshot(encoded)


def test_health_states_and_monotonic_bounded_history():
    """Handle test health states and monotonic bounded history."""
    health=HealthState()
    for i in range(100):health.transition(STATES[i%len(STATES)])
    assert health.history[-1]['seq']==100
    assert len(health.history)==64
    with pytest.raises(ValueError):health.transition('INVALID')


def test_task_queue_cancels_active_and_coalesces_pending():
    """Handle test task queue cancels active and coalesces pending."""
    jobs=RuntimeJobs();started=threading.Event();release=threading.Event();finished=threading.Event();results=[]
    def slow(token):started.set();release.wait(3);token.checkpoint();results.append('old')
    try:
        jobs.submit('snapshot',slow);assert started.wait(2)
        jobs.submit('snapshot',lambda token:results.append('obsolete'))
        jobs.submit('snapshot',lambda token:(results.append('latest'),finished.set()))
        release.set();assert finished.wait(2)
        assert results==['latest']
    finally:release.set();jobs.close()


def test_ping_answers_busy_work_without_waiting():
    """Handle test ping answers busy work without waiting."""
    runtime=NativeRuntime(0,'.');out=[];runtime.send=out.append
    started=threading.Event();release=threading.Event()
    try:
        runtime.jobs.submit('world',lambda token:(started.set(),release.wait(3)))
        assert started.wait(2)
        runtime.handle_ipc_message({'cmd':'ping'})
        assert out[-1]['type']=='pong' and out[-1]['health']['busy']
        runtime.handle_ipc_message({'cmd':'cancel'})
        assert runtime.health.current=='DEGRADED'
    finally:release.set();runtime.jobs.close()


def test_cancelled_world_cannot_replace_runtime_world(monkeypatch):
    """Handle test cancelled world cannot replace runtime world."""
    runtime=NativeRuntime(0,'.');runtime.ctx=context();runtime.slot_data={};runtime.send=lambda obj:None
    started=threading.Event();release=threading.Event()
    monkeypatch.setattr('wayfinder.runtime.world_loader.ensure_game_loaded',lambda *a,**kw:SimpleNamespace(game='Demo'))
    monkeypatch.setattr('wayfinder.runtime.apworld_catalog.select_world',lambda *a:SimpleNamespace(path='demo.apworld',game='Demo',sha256='hash',manifest={}))
    monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.require_dependencies',lambda *a:[])
    monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.reconstruction_key',lambda *a,**kw:'cancel-test')
    monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.tree_fingerprint',lambda *a:'test-environment')
    monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.environment_identity',lambda *a:{'core':'test-environment'})
    monkeypatch.setattr('wayfinder.runtime.apworld_compatibility.save_report',lambda *a:None)
    def build(*a,**kw):started.set();release.wait(3);return SimpleNamespace(world=SimpleNamespace(),warnings=[])
    monkeypatch.setattr('wayfinder.runtime.world_builder.build_world',build)
    try:
        runtime.rebuild_world();assert started.wait(2);runtime.jobs.cancel();release.set()
        runtime.jobs.thread.join(.1)
        assert runtime.built is None
    finally:release.set();runtime.jobs.close()


def test_runtime_snapshot_is_validated_and_stamped():
    """Handle test runtime snapshot is validated and stamped."""
    runtime=NativeRuntime(0,'.');runtime.ctx=context();runtime.client=object();out=[];done=threading.Event()
    def send(obj):
        """Handle send."""
        out.append(obj)
        if obj.get('type')=='snapshot':done.set()
    runtime.send=send;runtime.connection_id='connection'
    try:
        runtime.queue_snapshot();assert done.wait(3)
        data=decode_snapshot(next(obj for obj in out if obj.get('type')=='snapshot'))
        validate_snapshot(data,True)
        assert data['connection_id']=='connection' and data['snapshot_sequence']==1
    finally:runtime.jobs.close()


def test_events_and_errors_have_correlation_ids():
    """Handle test events and errors have correlation ids."""
    runtime=NativeRuntime(0,'.')
    class Socket:
        """Provide socket behavior."""
        def sendall(self,data):self.data=json.loads(data)
    runtime.client=Socket()
    try:
        runtime.send_error('WF_TEST','password=private',component='APWorld')
        data=runtime.client.data
        assert data['event_id'] and data['runtime_id'] and data['session_id']
        assert data['component']=='APWorld' and 'private' not in data['message']
    finally:runtime.jobs.close()


def test_map_coverage_uses_resolved_ids_and_reports_unknowns(tmp_path):
    """Handle test map coverage uses resolved ids and reports unknowns."""
    pack=MapPack(tmp_path,'',maps=[MapDefinition('area','a.png',title='Area')],markers=[MapMarker('Alias','area',1,2),MapMarker('Not in seed','area',2,3),MapMarker('Door','entrances',3,4,section_names=('Can Enter','Can Complete'))])
    snap=Snapshot(locations=[LocationEntry('Real','reachable'),LocationEntry('Missing','unknown')])
    report=map_intelligence(snap,pack,lambda marker,index:snap.locations[0] if marker.location_name=='Alias' else None)
    assert report['missing_markers']==['Missing']
    assert report['unknown_locations']==['Not in seed']
    assert report['unknown_entrances']==['Door']
    assert report['maps']['Real']==['Area']


def test_check_evidence_is_conservative_and_location_specific():
    """Handle test check evidence is conservative and location specific."""
    snap=Snapshot(slot_name='Player',rule_details={'Blocked':{'missing':[{'kind':'item','name':'Key'}]},'Other':{'missing':[{'kind':'item','name':'Boots'}]}},hints=[dict(item='Key',location='Remote check',finding_player='Friend',receiving_player='Player',item_flags=1),dict(item='Boots',location='Local check',finding_player='Player',receiving_player='Friend',item_flags=1)])
    progression,remote=check_evidence(snap)
    assert progression=={'Local check'} and remote=={'Blocked'}

def test_client_rejects_old_connection_after_new_connect(monkeypatch):
    """Handle test client rejects old connection after new connect."""
    monkeypatch.setenv('WF_RUNTIME_PORT','0')
    snapshots=[];statuses=[]
    client=WayFinderRuntimeClient(snapshots.append,lambda text:None,lambda *row:statuses.append(row))
    client._send=lambda payload:True
    client._protocol_compatible=True;client._session_id='session';client._transport_epoch=1;client._negotiated_capabilities={'seed_identity'}
    try:
        client.connect('host:38281','Player');connection=client._seed_gate.connection_id
        data=packet(connection=connection)
        client._handle_message({'type':'status','session_id':'session','name':'seed_identity','value':{'identity':data['seed_identity'],'connection_id':connection}},1)
        client._handle_message({'type':'snapshot','session_id':'session','data':data,'event_id':'evt'},1)
        assert len(snapshots)==1 and snapshots[0].event_id=='evt'
        client.connect('host:38281','Player')
        data['snapshot_sequence']=2
        client._handle_message({'type':'snapshot','session_id':'session','data':data},1)
        assert len(snapshots)==1
        assert statuses[-1][0]=='runtime_error'
    finally:client.close()


def test_restart_rearms_connection_delivery(monkeypatch):
    """Handle test restart rearms connection delivery."""
    monkeypatch.setenv('WF_RUNTIME_PORT','0')
    client=WayFinderRuntimeClient(lambda s:None,lambda s:None)
    client._last_connection=('host:38281','Player','');client._ever_connected=True
    client._drop_transport=lambda *args,**kw:None
    client._start_transport_retry=lambda:None
    try:
        client.restart_connection()
        assert not client._ever_connected
        assert client._pending[-1]['cmd']=='connect'
        assert client._pending[-1]['connection_id']==client._seed_gate.connection_id
    finally:client.close()


def test_rejected_refresh_does_not_advance_gui_sequence():
    """Handle test rejected refresh does not advance gui sequence."""
    from wayfinder.app.app import WayFinderApp
    from wayfinder.connection.runtime_client import _snapshot_from_dict
    app=WayFinderApp.__new__(WayFinderApp)
    gate=SnapshotGate();gate.begin('connection');gate.announce(packet()['seed_identity'],'connection')
    app.runtime_client=SimpleNamespace(_seed_gate=gate);app._closing=False;app.snapshot=_snapshot_from_dict(packet())
    app._snapshot_runtime_id='runtime';app._last_snapshot_sequence=1;app._runtime_identity=('host:38281',0,'player','demo')
    app._latest_refresh_id=3;app._append_log=lambda *a,**kw:None
    incoming=packet(4);incoming['refresh_id']=2
    app._apply_snapshot(_snapshot_from_dict(incoming))
    assert app._last_snapshot_sequence==1
    assert app.snapshot.snapshot_sequence==1


def test_checks_filters_and_real_tree_grouping():
    """Handle test checks filters and real tree grouping."""
    import tkinter as tk
    from tkinter import ttk
    from wayfinder.app.app import WayFinderApp
    try:
        root=tk.Tk()
    except tk.TclError:
        pytest.skip('Tk display unavailable')
    root.withdraw()
    app=WayFinderApp.__new__(WayFinderApp)
    app.root=root;app.settings={};app._page=lambda name:ttk.Frame(root);app.active_map_pack=None
    app.check_mode=tk.StringVar(value='All');app.check_area=tk.StringVar(value='All areas')
    app.check_unchecked_only=tk.BooleanVar(value=True);app.check_hinted_only=tk.BooleanVar();app.check_progression_only=tk.BooleanVar()
    app.snapshot=Snapshot(locations=[LocationEntry('A','reachable','North'),LocationEntry('B','out_of_logic','South'),LocationEntry('C','checked','North')])
    app._check_hint_flags=lambda:{}
    try:
        app._build_checks();app.check_group.set('Region');app._refresh_checks()
        groups=app.check_tree.get_children()
        assert {app.check_tree.item(i,'text') for i in groups}=={'North','South'}
        assert all(app.check_tree.get_children(i) for i in groups)
        app.check_mode.set('Completed');app._refresh_checks()
        assert len(app.check_tree.get_children())==1
        group=app.check_tree.get_children()[0]
        assert app.check_tree.item(app.check_tree.get_children(group)[0],'values')[0]=='C'
        app.check_group.set('Map');app.check_mode.set('Blocked');app._refresh_checks()
        group=app.check_tree.get_children()[0]
        assert app.check_tree.item(group,'text')=='Unmapped'
        assert app.check_tree.item(app.check_tree.get_children(group)[0],'values')[0]=='B'
    finally:root.destroy()


def test_crash_recovery_keeps_gui_and_restarts_runtime():
    """Handle test crash recovery keeps gui and restarts runtime."""
    from wayfinder.app.ui.reliability_ui import ReliabilityUI
    app=ReliabilityUI();app._closing=False;app._managed_runtime_process=SimpleNamespace(poll=lambda:7,returncode=7)
    app.snapshot=Snapshot(connected=True);app._append_log=lambda *a,**kw:None;app.runtime_health_title=SimpleNamespace(set=lambda x:None)
    app.health_labels={};app.root=SimpleNamespace(after=lambda *args:None)
    app._recovery_due=0;app._ap_connection_state='connected'
    calls=[];app._ensure_local_runtime_started=lambda:(calls.append('restart') or True)
    app.runtime_client=SimpleNamespace(_last_connection=('host','Player',''),restart_connection=lambda:calls.append('reconnect'))
    app._reliability_tick()
    assert calls==['restart','reconnect'] and app._recovery_attempts==1


def test_startup_selftest_reports_independent_checks():
    """Handle test startup selftest reports independent checks."""
    runtime=NativeRuntime(0,'.');runtime.ctx=context();runtime.listener_ready.set();runtime.ap_version=lambda:'test-core';out=[];runtime.send=out.append
    try:
        runtime.startup_self_test()
        checks=next(row['value'] for row in out if row.get('name')=='runtime_self_test')
        assert all(checks.values()) and len(checks)>=6
        assert runtime.health.current=='READY'
    finally:runtime.jobs.close()


def test_seed_cannot_change_without_a_new_connection_intent():
    """Handle test seed cannot change without a new connection intent."""
    gate=SnapshotGate();gate.begin('connection','host:38281','Player')
    assert gate.announce(packet()['seed_identity'],'connection')
    assert not gate.announce(packet(seed='another-seed')['seed_identity'],'connection')
    with pytest.raises(ValueError):gate.check(packet(2,seed='another-seed'))
