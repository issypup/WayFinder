"""Native runtime reliability operations, independent of the AP asyncio loop."""
import asyncio
import copy
import json
import time
import uuid
from pathlib import Path
from .reliability import HealthState, RuntimeJobs
from ..connection.identity import seed_identity, validate_snapshot
from ..connection.protocol import encode_snapshot, decode_snapshot, error_payload
from ..diagnostics import sanitize

from .ap_protocol import APProtocol

class NativeReliability(APProtocol):
    """Provide native reliability behavior."""
    def init_reliability(self):
        """Handle init reliability."""
        self.init_ap_inspector()
        self.health=HealthState(); self.connection_id=''; self.last_snapshot={}; self.world_preparation_status={}; self.jobs=RuntimeJobs(self.job_error,self.job_cancelled)
        from .apworld_compatibility import ReconstructionCache
        self.reconstruction_cache=ReconstructionCache()
        self.apworld_report=None
        self._world_preparation_started_at=0.0
        self._world_preparation_phase_started_at=0.0
        self._world_preparation_phase=''
        self._world_preparation_timings={}
        self.apworld_environment=None
        self.transition('STARTING','Runtime process created')
    def transition(self,state,reason=''):
        """Handle transition."""
        self.send_status('runtime_state',self.health.transition(state,reason))
    def component_health(self,name,state,detail):
        """Handle component health."""
        self.health.component(name,state,detail)
        self.send_status('component_health',dict(self.health.components))
    def world_preparation(self,phase,step,total,message,state='running',**details):
        """Handle world preparation."""
        now=time.perf_counter()
        phase=str(phase)
        if not self._world_preparation_started_at or (int(step)==1 and state=='running'):
            self._world_preparation_started_at=now
            self._world_preparation_phase_started_at=now
            self._world_preparation_phase=phase
            self._world_preparation_timings={}
        elif phase != self._world_preparation_phase:
            if self._world_preparation_phase and self._world_preparation_phase_started_at:
                self._world_preparation_timings[self._world_preparation_phase]=round(now-self._world_preparation_phase_started_at,3)
            self._world_preparation_phase_started_at=now
            self._world_preparation_phase=phase
        if state in {'complete','failed','cancelled'} and self._world_preparation_phase and self._world_preparation_phase_started_at:
            self._world_preparation_timings[self._world_preparation_phase]=round(now-self._world_preparation_phase_started_at,3)
        payload=dict(phase=phase,step=int(step),total=int(total),message=str(message),state=str(state),
                     elapsed=round(max(0.0,now-self._world_preparation_started_at),3),timings=dict(self._world_preparation_timings))
        payload.update({k:v for k,v in details.items() if v is not None})
        self.world_preparation_status=payload
        self.send_status('world_preparation',payload)
    def job_cancelled(self,token):
        """Handle job cancelled."""
        if token.key in {'world','snapshot'}:
            current=dict(self.world_preparation_status or {})
            self.world_preparation(current.get('phase','cancelled'),current.get('step',0),current.get('total',10),current.get('message','World preparation cancelled'),'cancelled')
    def job_error(self,token,exc):
        """Handle job error."""
        from .apworld_compatibility import persist_exception
        if token.key in {'world','snapshot'}:
            current=dict(self.world_preparation_status or {})
            self.world_preparation(current.get('phase','failed'),current.get('step',0),current.get('total',10),str(exc),'failed')
        try:
            if token.key=='world' and self.apworld_report:
                import traceback
                from .apworld_compatibility import save_report
                self.apworld_report.update(outcome='Failed',error=str(exc),traceback=''.join(traceback.format_exception(type(exc),exc,exc.__traceback__)))
                save_report(self.apworld_report)
                self.send_status('apworld_stage',dict(self.apworld_report))
            path=persist_exception(exc,component=token.key,job_id=token.id,apworld=self.apworld_report)
            self.send_status('apworld_error_report',path)
        except OSError as report_error:
            self.send_log('[APWORLD] Could not persist error report: '+str(report_error))
        self.transition('DEGRADED',token.key+' failed')
        self.component_health('APWorld' if token.key=='world' else 'Snapshot Pipeline' if token.key=='snapshot' else 'Logic Engine','error',str(exc))
        self.send_error('WF_RUNTIME_JOB_FAILED',str(exc),job_id=token.id,component=token.key)
    def send_error(self,code,message,**context):
        """Handle send error."""
        packet=error_payload(code,sanitize(str(message)))
        packet.update(component=context.pop('component','Native Runtime'),recoverable=context.pop("recoverable",True),context=context)
        self.send(packet)
    def frozen_context(self):
        """Handle frozen context."""
        if self.ctx is None:return None
        ctx=copy.copy(self.ctx)
        for key,value in vars(self.ctx).items():
            if isinstance(value,(dict,list,set)):
                try:setattr(ctx,key,copy.deepcopy(value))
                except (TypeError,ValueError):setattr(ctx,key,copy.copy(value))
        return ctx
    def rebuild_world(self):
        """Handle rebuild world."""
        from .world_builder import build_world
        from .world_loader import ensure_game_loaded
        ctx=self.frozen_context(); connection=self.connection_id
        if not ctx or not getattr(ctx,'game',''):return
        slot_data=copy.deepcopy(self.slot_data)
        def work(token):
            """Handle work."""
            from .apworld_catalog import select_world
            from .apworld_compatibility import require_dependencies, reconstruction_key, tree_fingerprint, save_report, environment_identity
            from ..setup import DEPENDENCIES_DIR
            self.transition('RECONSTRUCTING','Preparing connected APWorld')
            self.world_preparation('apworld',4,10,f'Loading APWorld for {ctx.game}', game=ctx.game, slot=ctx.auth or 'Player', progress_mode='indeterminate')
            self.apworld_report=None
            discovery_started=time.perf_counter()
            record=select_world(ctx.game,self.ap_root)
            discovery_ms=round((time.perf_counter()-discovery_started)*1000.0,3)
            report=dict(id=uuid.uuid4().hex,path=record.path,game=record.game,world_hash=record.sha256,
                        time=time.time(),connection=connection,stages=['Discovered','Manifest','Synced'],outcome='Running',profile='Live seed',
                        identity_method='archipelago.json' if record.manifest else 'Legacy literal fallback')
            self.apworld_report=report
            def stage(name):
                """Handle stage."""
                report['stages'].append(name)
                save_report(report)
                self.send_status('apworld_stage',dict(report))
            self.transition('RECONSTRUCTING','Building connected APWorld')
            self.component_health('APWorld','busy',ctx.game)
            self.world_preparation('dependencies',5,10,'Verifying world dependencies', game=ctx.game, slot=ctx.auth or 'Player', progress_mode='indeterminate')
            dependency_started=time.perf_counter()
            report['dependencies']=require_dependencies(record,DEPENDENCIES_DIR)
            dependency_ms=round((time.perf_counter()-dependency_started)*1000.0,3)
            dep_total=len(report['dependencies'])
            self.world_preparation('dependencies',5,10,f'Verified {dep_total} dependenc{'y' if dep_total==1 else 'ies'}', game=ctx.game, slot=ctx.auth or 'Player', progress_mode='determinate', progress_current=dep_total, progress_total=dep_total)
            stage('Dependencies');token.checkpoint()
            self.world_preparation('apworld',4,10,f'APWorld located: {Path(record.path).name}', game=ctx.game, slot=ctx.auth or 'Player', progress_mode='determinate', progress_current=1, progress_total=1, apworld=Path(record.path).name, apworld_path=str(record.path), apworld_source=str(getattr(record,'source','') or ''), apworld_version=str(getattr(record,'version','') or ''), identification=('archipelago.json' if getattr(record,'manifest',{}) else 'Legacy literal fallback'), dependency_count=dep_total)
            environment=environment_identity(self.ap_root,DEPENDENCIES_DIR)
            report['environment']=environment
            if self.apworld_environment is not None and self.apworld_environment!=environment:
                raise RuntimeError('Core or dependencies changed. Restart the native runtime before reconstruction.')
            self.apworld_environment=environment
            import_started=time.perf_counter()
            world_class=ensure_game_loaded(ctx.game,self.ap_root,selected_path=record.path)
            apworld_import_ms=round((time.perf_counter()-import_started)*1000.0,3); token.checkpoint()
            stage('Imported')
            key=reconstruction_key(record,self.ap_root,DEPENDENCIES_DIR,
                dict(connection=connection,identity=seed_identity(ctx,None),slot_data=slot_data,
                     players=tree_fingerprint(self.players_path) if self.players_path else ''), environment=environment)
            self.world_preparation('reconstructing',6,10,'Reconstructing seed logic', game=ctx.game, slot=ctx.auth or 'Player', progress_mode='indeterminate')
            reconstruction_started=time.perf_counter()
            built,hit=self.reconstruction_cache.get_or_build(key,lambda:build_world(world_class.game,ctx.auth or 'Player',slot_data,player_files_path=self.players_path or None))
            reconstruction_seconds=round(time.perf_counter()-reconstruction_started,3)
            self.world_preparation('reconstructing',6,10,('Loaded seed reconstruction from cache' if hit else 'Built seed reconstruction from APWorld'), game=ctx.game, slot=ctx.auth or 'Player', progress_mode='determinate', progress_current=1, progress_total=1, cache_hit=bool(hit), duration=reconstruction_seconds, logic_source=getattr(built,'logic_source','Unknown'), exact_logic=bool(getattr(built,'exact_logic',False)))
            report.update(cache_key=key,cache_hit=hit)
            token.checkpoint()
            if connection!=self.connection_id:return
            built._wayfinder_report_id=report['id']
            perf=dict(getattr(built,'performance_timings_ms',{}) or {})
            perf.update(apworld_catalog_scan=discovery_ms, dependency_validation=dependency_ms, apworld_import=apworld_import_ms)
            built.performance_timings_ms=perf
            report['performance_timings_ms']=dict(perf)
            self.built=built
            stage('Reconstructed')
            self.send_status('game_apworld_loaded',True); self.send_status('world_reconstructed',True)
            self.component_health('APWorld','ready',ctx.game)
            self.component_health('Logic Engine','ready' if getattr(built,'exact_logic',False) else 'degraded',f"World reconstructed • Logic source: {getattr(built,'logic_source','Unknown')}" if getattr(built,'exact_logic',False) else f"Approximate reconstruction • Logic source: {getattr(built,'logic_source','Default options — approximate')}")
            # set_notify creates asyncio tasks and must run on the AP loop.
            self.loop.call_soon_threadsafe(self._finish_world_subscriptions, connection, built)
            for warning in built.warnings:self.send_log('[APWorld compatibility] '+warning)
            self.send_status('seed_identity',dict(identity=seed_identity(ctx,built.world),connection_id=connection))
        self.jobs.submit('world',work)
    def _finish_world_subscriptions(self, connection, built):
        """Handle finish world subscriptions."""
        if connection != self.connection_id or built is not self.built:
            return
        self._subscribe_map_page_if_available()
        self._subscribe_player_position_if_available()
        self.queue_snapshot()
    def queue_live_update(self, cmd='', args=None):
        """Coalesce AP state packets and publish after CommonClient has applied them.

        Live packets often arrive in small bursts (RoomUpdate + ReceivedItems +
        DataStorage replies).  The old path called publish() from on_package,
        freezing the CommonContext too early and repeatedly cancelling the serial
        snapshot job.  A short event-loop debounce makes the final packet state
        authoritative while still feeling immediate in the UI.
        """
        args = args if isinstance(args, dict) else {}
        try:
            checked = len(args.get('checked_locations', []) or []) if 'checked_locations' in args else -1
        except Exception:
            checked = -1
        try:
            items = len(args.get('items', []) or []) if 'items' in args else -1
        except Exception:
            items = -1
        self.send_log(f"[LIVE-UPDATE] AP packet {cmd}: checked_payload={checked} items_payload={items}; scheduling snapshot")
        loop = self.loop
        if not loop or not loop.is_running():
            self.publish()
            return

        def schedule_debounced():
            """Handle schedule debounced."""
            previous = getattr(self, '_live_update_handle', None)
            if previous is not None:
                try:
                    previous.cancel()
                except Exception:
                    pass
            def fire():
                """Handle fire."""
                self._live_update_handle = None
                ctx = self.ctx
                try:
                    checked_now = len(getattr(ctx, 'checked_locations', set()) or set()) if ctx else 0
                except Exception:
                    checked_now = -1
                try:
                    received_now = len(getattr(ctx, 'items_received', []) or []) if ctx else 0
                except Exception:
                    received_now = -1
                self.send_log(f"[LIVE-UPDATE] publishing settled AP state: checked={checked_now} received_items={received_now}")
                self.queue_snapshot()
            self._live_update_handle = loop.call_later(0.075, fire)
        loop.call_soon_threadsafe(schedule_debounced)

    def publish(self,refresh_id=0):
        """Handle publish."""
        if not self.client:return
        if self.loop and self.loop.is_running():
            self.loop.call_soon_threadsafe(self.queue_snapshot,refresh_id)
        else:self.queue_snapshot(refresh_id)
    def queue_snapshot(self,refresh_id=0):
        """Handle queue snapshot."""
        ctx=self.frozen_context(); connection=self.connection_id; ignored=set(self.ignored_names)
        inspector_epoch=self.ap_inspector.epoch; inspector_revision=self.ap_inspector.check_revision
        def work(token):
            """Handle work."""
            from .snapshot import build_snapshot
            preparing_world = str((self.world_preparation_status or {}).get('state','')) == 'running'
            if preparing_world:
                self.world_preparation('logic',7,10,'Building regions, entrances and rules', game=str(getattr(ctx,'game','') or ''), slot=str(getattr(ctx,'auth','') or ''), progress_mode='indeterminate')
            self.transition('SYNCING','Preparing current snapshot')
            self.component_health('Snapshot Pipeline','busy','Serial snapshot job')
            built=self.built; self.sequence+=1
            snapshot_started=time.perf_counter()
            if ctx and built:
                ctx._wayfinder_cancel_check=token.checkpoint
                data=build_snapshot(ctx,built,ignored_names=ignored,sequence=self.sequence,refresh_id=refresh_id)
            else:
                data=dict(connected=bool(ctx and getattr(ctx,'slot',None)),server=str(getattr(ctx,'server_address','') or ''),slot_name=str(getattr(ctx,'auth','') or ''),game=str(getattr(ctx,'game','') or ''),team=int(getattr(ctx,'team',0) or 0),locations=[],inventory=[],reachability_available=False,error='World not reconstructed' if ctx and getattr(ctx,'slot',None) else '')
            snapshot_seconds=round(time.perf_counter()-snapshot_started,3)
            if preparing_world and built:
                total_locations=len(data.get('locations',[]) or [])
                self.world_preparation('logic',7,10,f'Evaluated {total_locations} locations', game=str(getattr(ctx,'game','') or ''), slot=str(getattr(ctx,'auth','') or ''), progress_mode='determinate', progress_current=total_locations, progress_total=total_locations, duration=snapshot_seconds, logic_source=getattr(built,'logic_source','Unknown'), exact_logic=bool(getattr(built,'exact_logic',False)) )
                self.world_preparation('initial_state',8,10,'Preparing tracker initial state', game=str(getattr(ctx,'game','') or ''), slot=str(getattr(ctx,'auth','') or ''), progress_mode='determinate', progress_current=total_locations, progress_total=total_locations, locations=total_locations, reachable=len([x for x in data.get('locations',[]) if x.get('status')=='reachable']))
            identity=seed_identity(ctx,built.world if built else None)
            data.update(seed_identity=identity,connection_id=connection,runtime_id=self.runtime_id,snapshot_sequence=self.sequence,refresh_id=refresh_id)
            validate_snapshot(data,True); token.checkpoint()
            if connection!=self.connection_id:return
            self.last_snapshot=data
            self._inspector_snapshot_epoch=inspector_epoch
            self._inspector_snapshot_revision=inspector_revision
            self.send_status('seed_identity',dict(identity=identity,connection_id=connection))
            self.send(encode_snapshot(data))
            if built and data.get('connected') and data.get('reachability_available') and self.apworld_report and self.apworld_report.get('connection')==connection and getattr(built,'_wayfinder_report_id',None)==self.apworld_report['id'] and self.apworld_report['stages'][-1]=='Reconstructed':
                from .apworld_compatibility import save_report
                self.apworld_report['stages'].append('Active')
                self.apworld_report['outcome']='Active'
                save_report(self.apworld_report)
                self.send_status('apworld_stage',dict(self.apworld_report))
            self.component_health('Snapshot Pipeline','ready','Validated generation '+str(self.sequence))
            self.component_health('Logic Engine','ready' if data.get('reachability_available',False) else 'degraded','Logic current' if data.get('reachability_available',False) else 'Reachability unavailable')
            self.transition('TRACKING' if data.get('connected') and data.get('reachability_available',False) else 'DEGRADED' if data.get('connected') else 'READY','Snapshot published')
            if refresh_id:self.send_status('refresh_status',dict(id=refresh_id,state='complete',message='Validated snapshot published'))
            self.send_status('recalculating',False)
            # GUI completes stages 9 (map) and 10 (ready) after the first snapshot is applied,
            # because map-pack matching and image-cache provenance live in the presentation process.
        self.jobs.submit('snapshot',work)
    def snapshot(self,refresh_id=0):
        # Console/path jobs consume the last atomic result instead of recalculating on IPC.
        """Handle snapshot."""
        return self.last_snapshot or dict(connected=False,locations=[],inventory=[],error='Waiting for first snapshot')
    def queue_path(self,target,request):
        """Handle queue path."""
        connection=self.connection_id; session=self.session_id
        def work(token):
            """Handle work."""
            result=self.path_result(target); token.checkpoint()
            if connection==self.connection_id and session==self.session_id:
                self.send(dict(type='path',id=request,data=result))
        self.jobs.submit('path',work)
    def startup_self_test(self):
        """Handle startup self test."""
        checks={'IPC listener':self.listener_ready.is_set(),'AP context':self.ctx is not None,'Archipelago Core':bool(self.ap_version()),'Task worker':self.jobs.thread.is_alive()}
        probe={'connected':False,'locations':[],'inventory':[],'snapshot_sequence':1}
        checks['Snapshot codec']=decode_snapshot(encode_snapshot(probe))==probe
        checks['Snapshot validation']=validate_snapshot(probe)==probe
        self._self_test_results=checks
        self.send_status('runtime_self_test',checks)
        if not all(checks.values()):raise RuntimeError('Runtime self-test failed: '+', '.join(k for k,v in checks.items() if not v))
        self.component_health('IPC','ready','Self-test passed')
        self.component_health('Native Runtime','ready','Self-test passed')
        self.component_health('Archipelago Core','ready',self.ap_version())
        self.transition('READY','Startup self-test passed')
