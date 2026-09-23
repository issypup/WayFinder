"""Connection inspector with packet evidence and paged value browsers."""
import time
import tkinter as tk
from tkinter import ttk
from ...diagnostics import sanitize
from ...connection.ap_inspector import PACKETS


class APInspectorUI:
    """Provide a p inspector u i behavior."""
    def _build_ap_inspector(self):
        """Handle build ap inspector."""
        page=self._page('AP Connection')
        ttk.Label(page,text='Archipelago connection inspector',style='Title.TLabel').pack(anchor='w')
        toolbar=ttk.Frame(page);toolbar.pack(fill='x',pady=8)
        for title,action in (('Refresh view','summary'),('Measure latency','probe'),('Refresh DataStorage','refresh_storage'),('Resynchronise','resync')):
            ttk.Button(toolbar,text=title,command=lambda a=action:self._api_request(a)).pack(side='left',padx=(0,6))
        self.api_message=tk.StringVar(value='Connect to inspect server packets and state.')
        ttk.Label(page,textvariable=self.api_message,wraplength=1100).pack(anchor='w')
        ttk.Label(page,text='Resynchronise refreshes items and relevant stored values on the current connection. Checked locations retain the Connected baseline plus RoomUpdate changes.',wraplength=1100).pack(anchor='w',pady=4)
        tabs=ttk.Notebook(page);tabs.pack(fill='both',expand=True,pady=8)
        frames={}
        for title in ('Overview','Packets','Check comparison','Slot data','DataStorage'):
            frame=ttk.Frame(tabs,padding=8);tabs.add(frame,text=title);frames[title]=frame
        self.api_overview=self._api_text(frames['Overview'],22)
        packets=frames['Packets']
        line=ttk.Frame(packets);line.pack(fill='x')
        ttk.Label(line,text='Packet type').pack(side='left')
        self.api_filter=tk.StringVar(value='All')
        dropdown=ttk.Combobox(line,textvariable=self.api_filter,values=('All',)+PACKETS,state='readonly',width=24)
        dropdown.pack(side='left',padx=6);dropdown.bind('<<ComboboxSelected>>',lambda e:self._api_render_packets())
        ttk.Label(line,text='Latest 100 packets; payload previews are bounded and credentials are redacted.').pack(side='left')
        self.api_counts=self._api_tree(packets,('direction','command','count','last'),height=5)
        self.api_counts.bind('<<TreeviewSelect>>',lambda e:self._api_latest_packet())
        self.api_packets=self._api_tree(packets,('time','direction','command'),height=7)
        self.api_packets.bind('<ButtonRelease-1>',lambda e:self._api_packet_details(manual=True))
        self.api_packets.bind('<KeyRelease>',lambda e:self._api_packet_details(manual=True))
        self.api_packet_text=self._api_text(packets,10)
        self.api_checks_message=tk.StringVar()
        ttk.Label(frames['Check comparison'],textvariable=self.api_checks_message,wraplength=1050).pack(anchor='w',pady=8)
        self.api_checks=self._api_tree(frames['Check comparison'],('id','name','server','wayfinder'),height=18)
        slot=frames['Slot data']
        ttk.Label(slot,text='AP server slot data from Connected. Expand a field to browse its children; double-click “More” for the next page.',wraplength=1000).pack(anchor='w')
        ttk.Button(slot,text='Reload slot-data browser',command=lambda:self._api_load_root('slot_data')).pack(anchor='w',pady=6)
        self.api_slot_tree=self._api_value_tree(slot)
        storage=frames['DataStorage']
        ttk.Label(storage,text='Values relevant to this slot, APWorld subscriptions and game-name matches. “Not fetched” differs from a server null value.',wraplength=1000).pack(anchor='w')
        self.api_storage=self._api_tree(storage,('key','reason','available','value'),height=6)
        self.api_storage.bind('<<TreeviewSelect>>',lambda e:self._api_storage_selected())
        ttk.Label(storage,text='The table shows live previews. Expanded values are a captured view; reload to inspect updated values.',wraplength=1000).pack(anchor='w')
        ttk.Button(storage,text='Reload selected value',command=self._api_reload_storage).pack(anchor='w',pady=6)
        self.api_storage_tree=self._api_value_tree(storage)
        self.api_data={};self.api_sequence=0;self.api_pending={};self.api_nodes={}
        self.api_epoch=None;self.api_browser_generation={'slot_data':0,'storage':0}
        self.api_storage_key='';self.api_last_packet_signature=None;self.api_last_poll=0;self.api_last_probe=0
        self.api_latest_choice=None
        self.root.after(1000,self._api_tick)

    def _api_text(self,parent,height):
        """Handle api text."""
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,pady=4)
        text=tk.Text(frame,height=height,wrap='word',state='disabled')
        scrollbar=ttk.Scrollbar(frame,command=text.yview);text.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');text.pack(fill='both',expand=True)
        return text

    def _api_tree(self,parent,columns,height=8):
        """Handle api tree."""
        frame=ttk.Frame(parent);frame.pack(fill='both',expand=True,pady=4)
        tree=ttk.Treeview(frame,columns=columns,show='headings',height=height)
        for column in columns:
            tree.heading(column,text=column.replace('_',' ').title());tree.column(column,width=160,minwidth=65)
        scrollbar=ttk.Scrollbar(frame,command=tree.yview);tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side='right',fill='y');tree.pack(fill='both',expand=True)
        return tree

    def _api_value_tree(self,parent):
        """Handle api value tree."""
        tree=self._api_tree(parent,('type','value'),height=17)
        tree.configure(show='tree headings');tree.heading('#0',text='Field / index');tree.column('#0',width=330)
        tree.bind('<<TreeviewOpen>>',lambda e,t=tree:self._api_expand(t))
        tree.bind('<Double-1>',lambda e,t=tree:self._api_expand(t,more=True))
        return tree

    def _api_write(self,widget,text):
        """Handle api write."""
        widget.configure(state='normal');widget.delete('1.0','end');widget.insert('1.0',sanitize(text));widget.configure(state='disabled')

    def _api_request(self,action='summary',**fields):
        """Handle api request."""
        self.api_sequence+=1
        ident=self.api_sequence
        if action in {'resync','probe','refresh_storage'}:
            fields.setdefault('epoch',self.api_epoch);self.api_last_probe=time.monotonic()
        if action=='summary':
            snapshot=self.snapshot
            checked=[row.address for row in snapshot.locations if row.status=='checked' and type(row.address) is int]
            fields['gui']=dict(checked=checked[:100000],truncated=len(checked)>100000,generation=snapshot.snapshot_sequence,
                               runtime_id=getattr(snapshot,'runtime_id',''),connection_id=getattr(snapshot,'connection_id',''))
        if not self.runtime_client.inspect_ap(action,id=ident,**fields):
            self.api_message.set('Native runtime is unavailable. Connect after completing Setup.')
            return None
        if action!='summary':self.api_message.set('Request sent: '+action.replace('_',' '))
        return ident

    def _api_tick(self):
        """Handle api tick."""
        if self._closing:return
        if getattr(self,'current_page','')=='AP Connection' and time.monotonic()-self.api_last_poll>=2:
            self.api_last_poll=time.monotonic();self._api_request()
            if self.api_data.get('connected') and time.monotonic()-self.api_last_probe>=15:self._api_request('probe')
        self.root.after(1000,self._api_tick)

    def _api_status(self,name,value):
        """Handle api status."""
        if not hasattr(self,'api_data'):return
        if name=='ap_inspector_error':
            self.api_message.set(sanitize(value.get('message','Inspector request failed')))
            self.api_pending.pop(value.get('id'),None)
        elif name=='ap_browser':self._api_browser_reply(value)
        elif name=='ap_inspector':
            if value.get('id',0)<self.api_data.get('id',0):return
            changed=value.get('epoch')!=self.api_epoch
            self.api_data=value;self.api_epoch=value.get('epoch')
            self.api_message.set(value.get('state','Unknown'))
            comparison=value.get('comparison',{});derived=value.get('derived',{})
            latency=value.get('latency_ms')
            age=max(0,int(time.time()-value['latency_time'])) if value.get('latency_time') else None
            latency_text='Not measured — use Measure latency' if latency is None else f'{latency} ms (measured {age}s ago)'
            activity=value.get('activity',{})
            resync=value.get('resync',{})
            resync_state=resync.get('state','Not requested') if isinstance(resync,dict) else str(resync or 'Not requested')
            issues=value.get('errors',[])
            lines=[f"Connection: {value.get('state')}\nGame: {value.get('game')}\nSlot: {value.get('slot_name')}",
                   f"\nLatency: {latency_text}\n{value.get('latency_basis','')}",
                   f"Packets in last 10 seconds: {activity.get('inbound_10s',0)} received / {activity.get('outbound_10s',0)} sent",
                   '\nAP SERVER EVIDENCE',f"Items: {value.get('items',{}).get('state','Unknown')}",
                   f"Next item index: {value.get('items',{}).get('expected_index')}",f"Confirmed checked locations: {comparison.get('server_count',0)}",
                   '\nAPWORLD-DERIVED STATE',f"World reconstructed: {derived.get('reconstructed',False)}; authoritative logic: {derived.get('exact_logic',False)}",f"Logic source: {derived.get('logic_source','Unknown')}",
                   '\nWAYFINDER INFERENCE',f"Reachability available: {derived.get('reachability',False)}; snapshot generation: {derived.get('snapshot_generation',0)}",
                   'Map matching, progression candidates and discrepancy comparisons are calculated by WayFinder.',
                   '\nRESYNCHRONISATION',f"State: {resync_state}",
                   '\nRECENT PROTOCOL ISSUES']
            if issues:
                lines.extend(issue.get('message','Unknown protocol issue') for issue in issues)
            else:
                lines.append('None since authentication.' if value.get('state')=='Authenticated' else 'None recorded.')
            self._api_write(self.api_overview,'\n'.join(lines))
            self._api_render_packets()
            if not comparison.get('authoritative'):status='Awaiting a Connected baseline; comparison unavailable.'
            elif comparison.get('pending'):status='WayFinder snapshot is still catching up. Differences below are provisional.'
            else:status=f"{comparison.get('total_discrepancies',0)} discrepancies. Server: {comparison.get('server_count',0)} checked; WayFinder: {comparison.get('wayfinder_count',0)} checked."
            self.api_checks_message.set(status+'\n'+comparison.get('target','Runtime snapshot')+'; '+comparison.get('basis','')+'\nShowing at most 300 differences, matched by numeric location ID.'+(' GUI comparison limited to 100,000 checks.' if comparison.get('truncated') else ''))
            self.api_checks.delete(*self.api_checks.get_children())
            for row in comparison.get('discrepancies',[]):self.api_checks.insert('','end',values=tuple(row.get(k,'') for k in ('id','name','server','wayfinder')))
            selected=self.api_storage_key
            self.api_storage.delete(*self.api_storage.get_children())
            for index,row in enumerate(value.get('storage',[])):
                iid=self.api_storage.insert('','end',iid=str(index),values=(row['key'],row['reason'],'Fetched' if row['available'] else 'Not fetched',row.get('value','')))
                if row['key']==selected:self.api_storage.selection_set(iid)
            if changed:
                self.api_latest_choice=None
                self.api_pending.clear();self.api_nodes.clear();self.api_storage_key=''
                self.api_storage_tree.delete(*self.api_storage_tree.get_children())
                self._api_load_root('slot_data')

    def _api_render_packets(self):
        """Handle api render packets."""
        data=self.api_data;filter_name=self.api_filter.get()
        signature=(self.api_epoch,filter_name,tuple((r['direction'],r['command'],r['count']) for r in data.get('counts',[])))
        if signature==self.api_last_packet_signature:return
        self.api_last_packet_signature=signature
        self.api_counts.delete(*self.api_counts.get_children())
        for row in data.get('counts',[]):
            if filter_name=='All' or row['command']==filter_name:
                iid=self.api_counts.insert('','end',values=(row['direction'],row['command'],row['count'],time.strftime('%H:%M:%S',time.localtime(row['last']))))
                if self.api_latest_choice==(row['direction'],row['command']):self.api_counts.selection_set(iid)
        selected=self.api_packets.selection()
        self.api_packets.delete(*self.api_packets.get_children())
        for row in reversed(data.get('packets',[])):
            if filter_name=='All' or row['command']==filter_name:
                self.api_packets.insert('','end',iid=str(row['id']),values=(time.strftime('%H:%M:%S',time.localtime(row['time'])),row['direction'],row['command']))
        if selected and self.api_packets.exists(selected[0]):self.api_packets.selection_set(selected[0])
        elif self.api_packets.get_children():self.api_packets.selection_set(self.api_packets.get_children()[0])
        self._api_packet_details()

    def _api_packet_details(self,manual=False):
        """Handle api packet details."""
        if manual:self.api_latest_choice=None
        if self.api_latest_choice:
            direction,command=self.api_latest_choice
            row=next((r for r in self.api_data.get('latest',[]) if r['direction']==direction and r['command']==command),None)
            if row:self._api_write(self.api_packet_text,'Latest '+direction+' '+command+'\n'+row['preview'])
            return
        selected=self.api_packets.selection()
        row=next((r for r in self.api_data.get('packets',[]) if selected and str(r['id'])==selected[0]),None)
        self._api_write(self.api_packet_text,row['preview'] if row else 'Select a packet to inspect its fields.')

    def _api_latest_packet(self):
        """Handle api latest packet."""
        selected=self.api_counts.selection()
        if not selected:return
        direction,command,*_=self.api_counts.item(selected[0],'values')
        self.api_latest_choice=direction,command
        row=next((r for r in self.api_data.get('latest',[]) if r['direction']==direction and r['command']==command),None)
        if row:self._api_write(self.api_packet_text,'Latest '+direction+' '+command+'\n'+row['preview'])

    def _api_load_root(self,scope,key=''):
        """Handle api load root."""
        if not self.api_epoch:return
        tree=self.api_slot_tree if scope=='slot_data' else self.api_storage_tree
        self.api_browser_generation[scope]+=1
        tree.delete(*tree.get_children())
        self.api_nodes={k:v for k,v in self.api_nodes.items() if k[0] is not tree}
        self._api_load_branch(tree,'',scope,key,[],0)

    def _api_load_branch(self,tree,parent,scope,key,path,offset):
        """Handle api load branch."""
        ident=self._api_request('browse',scope=scope,key=key,path=path,offset=offset,epoch=self.api_epoch)
        if ident is not None:
            self.api_pending[ident]=(tree,parent,scope,key,path,offset,self.api_browser_generation[scope],self.api_epoch)

    def _api_expand(self,tree,more=False):
        """Handle api expand."""
        iid=tree.focus();node=self.api_nodes.get((tree,iid))
        if not node:return
        if node.get('more') and more:
            tree.delete(iid);self.api_nodes.pop((tree,iid),None)
            self._api_load_branch(tree,node['parent'],node['scope'],node['key'],node['path'],node['offset'])
        elif not node.get('more') and not node.get('loaded'):
            node['loaded']=True
            self._api_load_branch(tree,iid,node['scope'],node['key'],node['path'],0)

    def _api_browser_reply(self,value):
        """Handle api browser reply."""
        pending=self.api_pending.pop(value.get('id'),None)
        if not pending:return
        tree,parent,scope,key,path,offset,generation,epoch=pending
        if epoch!=self.api_epoch or value.get('epoch')!=epoch or generation!=self.api_browser_generation[scope]:return
        if parent and not tree.exists(parent):return
        if offset==0:tree.delete(*tree.get_children(parent))
        for row in value.get('rows',[]):
            iid=tree.insert(parent,'end',text=f"{row['label']}  [{row['key']}]",values=(row['type'],row['summary']))
            if row['expandable']:
                tree.insert(iid,'end',text='Loading…')
                self.api_nodes[tree,iid]=dict(scope=scope,key=key,path=row['path'],loaded=False)
        if 'value' in value:tree.insert(parent,'end',text='Value',values=('value',value['value']))
        if value.get('next') is not None:
            iid=tree.insert(parent,'end',text=f"More… ({value['next']} / {value['total']})",values=('page','Double-click to load'))
            self.api_nodes[tree,iid]=dict(scope=scope,key=key,path=path,offset=value['next'],parent=parent,more=True)

    def _api_storage_selected(self):
        """Handle api storage selected."""
        selected=self.api_storage.selection()
        if selected:
            rows=self.api_data.get('storage',[])
            index=int(selected[0])
            if index<len(rows) and rows[index]['key']!=self.api_storage_key:
                self.api_storage_key=rows[index]['key'];self._api_load_root('storage',self.api_storage_key)

    def _api_reload_storage(self):
        """Handle api reload storage."""
        if self.api_storage_key:self._api_load_root('storage',self.api_storage_key)
        else:self.api_message.set('Select a DataStorage key first.')
