"""AP inspection and read-only refresh operations on the AP asyncio loop."""
import asyncio
import functools
import time
from ..diagnostics import sanitize

from ..connection.ap_inspector import APInspector, browse, preview


def install_packet_observer(module):
    """Capture packets before CommonClient mutates state or rejects a packet.

    Dispatch through the context; avoid a global reference to a particular
    runtime so repeated context creation cannot attach stale observers.
    """
    original=module.process_server_cmd
    if getattr(original,'_wayfinder_observer',False):return
    @functools.wraps(original)
    async def observed(ctx,args):
        """Handle observed."""
        runtime=getattr(ctx,'_wayfinder_runtime',None)
        if runtime:
            try:runtime.ap_inspector.record('IN',args.get('cmd','Unknown'),args,len(getattr(ctx,'items_received',[])))
            except Exception as exc:runtime.ap_inspector.issue('Inspector could not summarize packet: '+str(exc))
        try:
            return await original(ctx,args)
        except Exception as exc:
            if runtime:runtime.ap_inspector.issue('Core rejected packet: '+str(exc))
            raise
        finally:
            if runtime:
                try:runtime.after_ap_packet(args)
                except Exception as exc:runtime.ap_inspector.issue('Inspector post-processing failed: '+str(exc))
    observed._wayfinder_observer=True
    module.process_server_cmd=observed


class APProtocol:
    """Provide a p protocol behavior."""
    def init_ap_inspector(self):
        """Handle init ap inspector."""
        self.ap_inspector=APInspector()
        self._last_ap_probe=0
        self._inspector_snapshot_epoch=None
        self._inspector_snapshot_revision=None

    def relevant_storage(self):
        """Handle relevant storage."""
        ctx=self.ctx
        if not ctx or getattr(ctx,'slot',None) is None:return {}
        team,slot=getattr(ctx,'team',0),ctx.slot
        reasons={f'_read_hints_{team}_{slot}':'Current slot hints',f'_read_slot_data_{slot}':'Current slot data',
                 f'_read_client_status_{team}_{slot}':'Current slot server status'}
        for field,title in (('resolved_map_page_setting_key','APWorld current map'),('resolved_player_position_setting_key','APWorld player position')):
            key=getattr(self.built,field,'')
            if key:reasons[key]=title
        game=str(getattr(ctx,'game','')).casefold()
        for key in getattr(ctx,'stored_data_notification_keys',set()):
            if not str(key).startswith('_read_hints_') or str(key)==f'_read_hints_{team}_{slot}':
                reasons.setdefault(str(key),'Subscribed by the current runtime')
        for key in getattr(ctx,'stored_data',{}):
            if game and game in str(key).casefold():reasons.setdefault(str(key),'Game-name match (WayFinder inference)')
        return reasons

    def storage_rows(self):
        """Handle storage rows."""
        stored=getattr(self.ctx,'stored_data',{}) if self.ctx else {}
        rows=[]
        for key,reason in list(self.relevant_storage().items())[:256]:
            protected=sanitize({key:'value'}).get(key)=='[REDACTED]'
            value='[REDACTED]' if protected else stored.get(key)
            rows.append(dict(key=key,reason=reason,available=key in stored,value=preview(value,250) if key in stored else 'Not fetched'))
        return rows

    def ap_connection_open(self):
        """Handle ap connection open."""
        server=getattr(self.ctx,'server',None) if self.ctx else None
        socket=getattr(server,'socket',None)
        return bool(self.ctx and getattr(self.ctx,'slot',None) is not None and server and not getattr(socket,'closed',False) and getattr(socket,'open',True))

    def after_ap_packet(self,args):
        """Handle after ap packet."""
        inspector=self.ap_inspector
        if args.get('cmd')=='Retrieved' and args.get('wf_inspector_request')==inspector.resync.get('request'):
            refreshed=args.get('keys',{}).get(f'_read_slot_data_{getattr(self.ctx,"slot",None)}')
            if isinstance(refreshed,dict) and refreshed!=getattr(self.ctx,'slot_data',{}):
                inspector.resync['slot_data']='Changed since Connected; reconnect to confirm seed identity'
                inspector.issue(inspector.resync['slot_data'])
            elif isinstance(refreshed,dict):inspector.resync['slot_data']='Matches Connected identity'

    async def inspector_request(self,msg):
        """Handle inspector request."""
        request_id=msg.get('id',0)
        try:
            action=msg.get('action','summary')
            if action in {'resync','probe','refresh_storage'}:
                if msg.get('epoch') is not None and msg['epoch']!=self.ap_inspector.epoch:
                    raise ValueError('Connection changed; refresh the inspector before requesting server state')
                if not self.ap_connection_open():
                    raise ValueError('Connect to an AP server first')
                if action=='resync' and self.ap_inspector.resync.get('state')=='Waiting':
                    self.ap_inspector.summary()
                    if self.ap_inspector.resync.get('state')=='Waiting':
                        raise ValueError('A resynchronisation is already waiting for server replies')
                if time.monotonic()-self._last_ap_probe<2:
                    raise ValueError('Please wait two seconds between server requests')
                self._last_ap_probe=time.monotonic()
                nonce=self.ap_inspector.probe()
                keys=list(self.relevant_storage()) if action!='probe' else []
                if len(keys)>256:keys=keys[:256]
                packets=[dict(cmd='Get',keys=keys,wf_inspector_request=nonce)]
                if action=='resync':
                    self.ap_inspector.resync=dict(state='Waiting',request=nonce,started=time.monotonic(),
                        items='Waiting for index zero',storage='Waiting',checks='Using last Connected baseline and RoomUpdate deltas')
                    packets.insert(0,dict(cmd='Sync'))
                    # Restore the AP-core checked cache from observed server evidence.
                    # Never infer/send LocationChecks from GUI statuses.
                    if self.ap_inspector.authoritative:
                        self.ctx.checked_locations=set(self.ap_inspector.checked)
                        self.ctx.missing_locations=self.ap_inspector.locations-self.ap_inspector.checked
                await self.ctx.send_msgs(packets)
                self.publish()
            elif action=='browse':
                if msg.get('epoch')!=self.ap_inspector.epoch:raise ValueError('Connection changed; refresh this browser')
                scope=msg.get('scope')
                if scope=='slot_data':value=getattr(self.ctx,'slot_data',{}) if self.ctx else {}
                elif scope=='storage':
                    key=msg.get('key','')
                    if key not in self.relevant_storage():raise ValueError('Key is not relevant to the current world')
                    value='[REDACTED]' if sanitize({key:'value'}).get(key)=='[REDACTED]' else getattr(self.ctx,'stored_data',{}).get(key)
                else:raise ValueError('Unknown browser scope')
                result=browse(value,msg.get('path',[]),msg.get('offset',0))
                result.update(id=request_id,epoch=self.ap_inspector.epoch,scope=scope,key=msg.get('key',''))
                self.send_status('ap_browser',sanitize(result))
                return
            elif action!='summary':raise ValueError('Unknown inspector action')
            summary=self.ap_inspector.summary()
            connected=self.ap_connection_open()
            summary.update(id=request_id,connected=connected,game=str(getattr(self.ctx,'game','') or ''),
                slot_name=str(getattr(self.ctx,'auth','') or ''),
                comparison=self.ap_inspector.comparison(self.last_snapshot,self._inspector_snapshot_revision,self._inspector_snapshot_epoch),
                storage=self.storage_rows(),
                derived=dict(reconstructed=self.built is not None,exact_logic=bool(getattr(self.built,'exact_logic',False)),logic_source=str(getattr(self.built,'logic_source','Unknown')),
                             snapshot_generation=self.last_snapshot.get('snapshot_sequence',0),reachability=self.last_snapshot.get('reachability_available',False)),
                provenance=dict(server='Room, slot data, received items, checked IDs, DataStorage',
                    apworld='Regions, entrances, item definitions and access rules',
                    inference='Reachability evaluation, map matching, progression candidates and discrepancy comparison'))
            gui=msg.get('gui')
            if isinstance(gui,dict) and isinstance(gui.get('checked'),list):
                checked={ident for ident in gui['checked'][:100000] if type(ident) is int}
                names={r.get('address'):r.get('name') for r in self.last_snapshot.get('locations',[])}
                displayed=dict(locations=[dict(address=ident,status='checked',name=names.get(ident,str(ident))) for ident in checked])
                comparison=self.ap_inspector.comparison(displayed,self._inspector_snapshot_revision,self._inspector_snapshot_epoch)
                comparison['pending']=comparison['pending'] or gui.get('generation')!=self.last_snapshot.get('snapshot_sequence') or gui.get('runtime_id')!=self.runtime_id or gui.get('connection_id')!=self.connection_id
                comparison.update(target='Displayed GUI snapshot',displayed_generation=gui.get('generation'),truncated=bool(gui.get('truncated')))
                for row in comparison['discrepancies']:
                    row['name']=names.get(row['id'],row['name'])
                    if row['server']=='Checked':row['wayfinder']='No checked entry in GUI'
                summary['comparison']=comparison
            if not connected:summary['state']='Offline — packet history is from the last connection'
            self.send_status('ap_inspector',sanitize(summary))
        except Exception as exc:
            self.send_status('ap_inspector_error',dict(id=request_id,message=sanitize(str(exc))))
