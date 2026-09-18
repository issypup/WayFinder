"""Seed and component-health UI, and supervised runtime recovery."""
import json
import time
import tkinter as tk
from tkinter import ttk
from pathlib import Path
from ...runtime.reliability import COMPONENTS
from ...connection.identity import validate_identity, normal_server
from ...maps.intelligence import map_intelligence
from ...diagnostics import sanitize

from .apworld_ui import APWorldUI

class ReliabilityUI(APWorldUI):
    """Provide reliability u i behavior."""
    def _build_seed_page(self):
        """Handle build seed page."""
        p=self._page('Seed')
        ttk.Label(p,text='Seed identity & safe resume',style='Title.TLabel').pack(anchor='w')
        self.seed_fields={key:tk.StringVar(value='Not confirmed') for key in ('server','seed','slot','slot_name','team','game','apworld_version','slot_data_fingerprint','id')}
        for key,value in self.seed_fields.items():
            row=ttk.Frame(p); row.pack(fill='x',pady=3)
            ttk.Label(row,text=key.replace('_',' ').title(),width=25).pack(side='left')
            ttk.Label(row,textvariable=value,wraplength=850).pack(side='left')
        self.seed_resume_status=tk.StringVar(value='Previous progress is only reused after the live seed identity matches.')
        ttk.Label(p,textvariable=self.seed_resume_status,wraplength=1000).pack(anchor='w',pady=12)
        ttk.Button(p,text='Resume previous seed',command=self._resume_seed).pack(anchor='w')
    def _resume_seed(self):
        # reliability_ui lives in wayfinder.app.ui; app.py is one package level up.
        # Build the state path from the storage API instead of importing app.py,
        # which also avoids a circular GUI-module dependency.
        """Handle resume seed."""
        from wayfinder.storage import app_data_root
        state_path = app_data_root() / 'last_snapshot.json'
        if self.snapshot.connected:
            self.seed_resume_status.set('Disconnect from the current seed before resuming another.');return
        try:
            data=json.loads(state_path.read_text(encoding='utf-8')); identity=validate_identity(data.get('seed_identity'))
            if not identity.get('complete'):raise ValueError('Previous seed identity is incomplete; connect manually to confirm it.')
            host,port=self._split_server_port(identity['server'])
            self.server_host_var.set(host);self.server_port_var.set(port or '38281');self.name_var.set(identity['slot_name'])
            self._resume_expected_seed=identity['id']
            self.seed_resume_status.set('Connecting; waiting for the server to confirm the previous seed.')
            self._connect_disconnect_clicked()
        except (OSError,ValueError,TypeError) as exc:self.seed_resume_status.set(str(exc))
    def _build_runtime_health(self):
        """Handle build runtime health."""
        p=self._page('Runtime Health')
        ttk.Label(p,text='Runtime health',style='Title.TLabel').pack(anchor='w')
        self.runtime_health_title=tk.StringVar(value='OFFLINE')
        ttk.Label(p,textvariable=self.runtime_health_title,style='Title.TLabel').pack(anchor='w',pady=10)
        self.health_labels={}
        for name in COMPONENTS:
            label=ttk.Label(p,text='● '+name+': not checked',wraplength=1100)
            label.pack(anchor='w',pady=6);self.health_labels[name]=label
        self.runtime_test_status=tk.StringVar(value='Startup self-test has not run.')
        ttk.Label(p,textvariable=self.runtime_test_status,wraplength=1000).pack(anchor='w',pady=12)
        ttk.Button(p,text='Restart runtime',command=self._restart_runtime).pack(anchor='w')
        ttk.Button(p,text='Cancel expensive jobs',command=lambda:self.runtime_client._send({'cmd':'cancel'})).pack(anchor='w',pady=8)
        self.root.after(1000,self._reliability_tick)
    def _build_map_intelligence(self):
        """Handle build map intelligence."""
        p=self._page('Map Intelligence')
        ttk.Label(p,text='Map-pack intelligence',style='Title.TLabel').pack(anchor='w')
        ttk.Label(p,text='Unknown pack references can be optional or absent from this seed. Reports do not change check status.',wraplength=1050).pack(anchor='w',pady=8)
        ttk.Button(p,text='Refresh report',command=self._refresh_map_intelligence).pack(anchor='w')
        self.map_intelligence_text=tk.Text(p,wrap='word',height=25)
        self.map_intelligence_text.pack(fill='both',expand=True,pady=10)
        self.map_intelligence_text.configure(state='disabled')
    def _map_coverage(self):
        """Handle map coverage."""
        pack=getattr(self,'active_map_pack',None)
        key=(id(self.snapshot),id(pack))
        if getattr(self,'_coverage_key',None)!=key:
            self._coverage_report=map_intelligence(self.snapshot,pack,lambda m,i:self._map_marker_member_location(m,i))
            self._coverage_key=key
        return self._coverage_report
    def _refresh_map_intelligence(self):
        """Handle refresh map intelligence."""
        if not hasattr(self,'map_intelligence_text'):return
        report=self._map_coverage()
        lines=['Pack: '+str(getattr(getattr(self,'active_map_pack',None),'display_name','No active pack'))]
        for key,title in (('missing_markers','Live checks without a marker'),('unknown_locations','Unknown location references'),('unknown_live_locations','Unknown live check statuses'),('unknown_entrances','Unknown entrance references')):
            rows=report[key];lines.extend(['',f'{title}: {len(rows)}',*rows] if rows else ['',title+': None'])
        widget=self.map_intelligence_text;widget.configure(state='normal');widget.delete('1.0','end');widget.insert('end',sanitize('\n'.join(lines)));widget.configure(state='disabled')
    def _feature_status(self,name,value):
        """Handle feature status."""
        self._aw_runtime_status(name,value)
        self._api_status(name,value)
        if name=='component_health' and isinstance(value,dict):self._component_health=value
        elif name=='runtime_self_test':
            if hasattr(self,'runtime_test_status'):self.runtime_test_status.set('Self-test: '+', '.join(k+(': passed' if v else ': FAILED') for k,v in value.items()))
        elif name=='runtime_watchdog':
            self._watchdog=value
            if value.get('alive') is False and getattr(self,'_managed_runtime_process',None) is not None:
                self._restart_runtime(manual=False)
        elif name=='runtime_error':
            self._append_log(value.get('error_code','WF_RUNTIME_ERROR')+': '+value.get('message',''),category='RUNTIME',level='ERROR',event_id=value.get('event_id'))
            self._runtime_state_name='DEGRADED' if value.get('recoverable') else 'ERROR'
            component=value.get('component','Native Runtime')
            health=getattr(self,'_component_health',{});health[component]={'state':'error','detail':value.get('message','')};self._component_health=health
        elif name=='seed_identity' and isinstance(value,dict):
            identity=value.get('identity',{})
            self._confirmed_seed=identity
            for key,var in getattr(self,'seed_fields',{}).items():var.set(sanitize(str(identity.get(key,'Not confirmed'))))
            expected=getattr(self,'_resume_expected_seed','')
            if expected and hasattr(self,'seed_resume_status'):
                self.seed_resume_status.set('Previous seed confirmed. Live state will replace the saved view.' if identity.get('id')==expected else 'The server reports a different seed. Previous progress will not be applied.')
    def _restart_runtime(self,manual=True):
        """Handle restart runtime."""
        from ...runtime.process_manager import stop_process
        stop_process(getattr(self,'_managed_runtime_process',None))
        self._recovery_due=time.monotonic()+1
        self._restart_requested=manual
    def _reliability_tick(self):
        """Handle reliability tick."""
        if self._closing:return
        proc=getattr(self,'_managed_runtime_process',None)
        health=dict(getattr(self,'_component_health',{}))
        health['GUI']={'state':'ready','detail':'Responsive'}
        ipc=getattr(self,'runtime_client_transport_state','idle')
        health['IPC']={'state':'ready' if ipc=='connected' else 'waiting','detail':ipc}
        health['Map Engine']={'state':'ready' if getattr(self,'active_map_pack',None) else 'waiting','detail':'Pack loaded' if getattr(self,'active_map_pack',None) else 'No active pack'}
        if proc is None:health['Native Runtime']={'state':'offline','detail':'Not started'}
        elif proc.poll() is not None:
            for name in ('AP Server','APWorld','Logic Engine','Snapshot Pipeline'):
                health[name]={'state':'offline','detail':'Runtime unavailable; previous data is stale'}
            health['Native Runtime']={'state':'error','detail':f'Process exited ({proc.returncode})'}
            self._runtime_state_name='ERROR'
            if not hasattr(self,'_recovery_due'):
                self._recovery_due=time.monotonic()+2;self._append_log('Runtime exited; recovery scheduled.',category='RUNTIME',level='ERROR')
                self.snapshot.stale=True;self.snapshot.connected=False;self._state_is_stale=True
            attempts=getattr(self,'_recovery_attempts',0)
            if time.monotonic()>=self._recovery_due and (attempts<3 or getattr(self,'_restart_requested',False)):
                self._recovery_attempts=attempts+1;self._restart_requested=False;self._recovery_due=time.monotonic()+min(30,2**(attempts+2))
                self._managed_runtime_process=None
                if self._ensure_local_runtime_started():
                    self._runtime_state_name='STARTING'
                    connection=getattr(self.runtime_client,'_last_connection',None)
                    self.runtime_client.restart_connection()
                else:self._managed_runtime_process=proc
        busy=getattr(self,'_watchdog',{})
        title=str(getattr(self,'_runtime_state_name','OFFLINE')).upper()
        if busy.get('busy'):title+=' — busy: '+busy.get('job','')+f" ({int(busy.get('busy_seconds',0))}s)"
        if title=='TRACKING':
            if not hasattr(self,'_tracking_since'):self._tracking_since=time.monotonic()
            elif time.monotonic()-self._tracking_since>60:self._recovery_attempts=0
        elif hasattr(self,'_tracking_since'):del self._tracking_since
        # Updating ttk widgets can trigger Windows theme/layout work.  Keep the
        # health model current, but only repaint this page while it is visible.
        if getattr(self,'current_page','') == 'Runtime Health':
            if self.runtime_health_title.get() != title:
                self.runtime_health_title.set(title)
            colors={'ready':'#2c9b68','error':'#d94b4b','offline':'#d28a28','waiting':'#d28a28','busy':'#d28a28','degraded':'#d28a28'}
            cache=getattr(self,'_runtime_health_render_cache',{})
            for name,label in self.health_labels.items():
                row=health.get(name,{'state':'waiting','detail':'Not checked'})
                text=sanitize('● '+name+': '+row.get('detail','')); color=colors.get(row.get('state'),'#d28a28')
                if cache.get(name)!=(text,color):
                    label.configure(text=text,foreground=color); cache[name]=(text,color)
            self._runtime_health_render_cache=cache
        self.root.after(1000,self._reliability_tick)
