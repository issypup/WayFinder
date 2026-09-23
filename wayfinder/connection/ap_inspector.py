"""Bounded, redacted AP packet evidence, independent of reconstructed logic."""
from collections import Counter, deque
import json
import time
import uuid
from ..diagnostics import sanitize

PACKETS = ('RoomInfo', 'Connected', 'ReceivedItems', 'LocationInfo', 'RoomUpdate',
           'Retrieved', 'SetReply', 'DataPackage', 'ConnectionRefused', 'InvalidPacket',
           'PrintJSON', 'Bounced', 'Connect', 'Get', 'Sync', 'SetNotify')


def preview(value, limit=4096):
    """Redact first; cap structure traversal as well as retained bytes."""
    budget = [300]
    def small(v, depth=0):
        """Handle small."""
        budget[0] -= 1
        if budget[0] < 0 or depth > 12:
            return '… preview limit'
        if hasattr(v, '_asdict'):
            v = v._asdict()
        if isinstance(v, dict):
            out = {}
            for key, item in v.items():
                if budget[0] <= 0:
                    out['…'] = 'preview limit'; break
                protected=sanitize({str(key):'value'}).get(str(key))=='[REDACTED]'
                out[str(key)[:200]] = '[REDACTED]' if protected else small(item, depth+1)
            return out
        if isinstance(v, (list, tuple, set)):
            out = []
            for item in v:
                if budget[0] <= 0:
                    out.append('… preview limit'); break
                out.append(small(item, depth+1))
            return out
        if isinstance(v, str):
            return sanitize(v)[:2048]
        return v if isinstance(v, (int, float, bool, type(None))) else str(v)[:200]
    text = json.dumps(sanitize(small(value)), ensure_ascii=False, indent=2)
    encoded=text.encode('utf-8')
    return encoded[:limit].decode('utf-8',errors='ignore') + ('\n… preview truncated; use the value browser for state' if len(encoded)>limit else '')


def browse(value, path=(), offset=0, page_size=100):
    """Page only one level of a value, so very large slot data stays usable."""
    if not isinstance(path, (list, tuple)) or len(path)>64:
        raise ValueError('Invalid value path')
    for key in path:
        if isinstance(key, str) and sanitize({key: 'value'}).get(key) == '[REDACTED]':
            value = '[REDACTED]'; break
        if isinstance(value, dict):
            value = value[key]
        elif isinstance(value, (tuple, list)) and type(key) is int:
            value = value[key]
        else:
            raise ValueError('Value path is no longer available')
    offset = max(0, int(offset))
    rows = []
    if isinstance(value, dict):
        from itertools import islice
        items = islice(value.items(), offset, offset+page_size)
        total = len(value)
    elif isinstance(value, (list, tuple)):
        items = enumerate(value[offset:offset+page_size], offset)
        total = len(value)
    else:
        return dict(path=list(path), rows=[], total=0, next=None, value=preview(value,16000))
    for key, item in items:
        protected = isinstance(key,str) and sanitize({key:'value'}).get(key)=='[REDACTED]'
        if protected: item='[REDACTED]'
        container = isinstance(item, (dict,list,tuple))
        summary = f'{len(item)} entries' if container else preview(item,300)
        rows.append(dict(key=key,label=str(key).replace('_',' ').strip().capitalize(),type=type(item).__name__,
                         summary=summary,expandable=container,path=list(path)+[key]))
    return dict(path=list(path),rows=rows,total=total,next=offset+page_size if offset+page_size<total else None)


class APInspector:
    """Provide a p inspector behavior."""
    def __init__(self):
        """Handle init."""
        self.reset()

    def reset(self):
        """Handle reset."""
        self.epoch=uuid.uuid4().hex
        self.started=time.time(); self.state='Offline'
        self.history=deque(maxlen=100); self.counts=Counter(); self.last={};self.latest={}
        self.activity=deque(maxlen=2000); self.errors=deque(maxlen=30)
        self.expected_index=None; self.item_state='Awaiting full inventory'
        self.checked=set(); self.locations=set(); self.authoritative=False
        self.check_revision=0; self.serial=0
        self.probes={}; self.latencies=deque(maxlen=20); self.latency_time=None
        self.resync=dict(state='Not requested')

    def record(self, direction, cmd, args, before_count=None):
        """Handle record."""
        if direction=='IN' and cmd=='RoomInfo':
            self.reset(); self.state='Room announced; awaiting login'
        cmd=str(cmd)[:80]
        if len(self.counts)>64 and (direction,cmd) not in self.counts:
            cmd='Other'
        self.serial+=1
        entry=dict(id=self.serial,time=time.time(),direction=direction,command=cmd,preview=preview(args))
        self.history.append(entry);self.counts[direction,cmd]+=1;self.last[direction,cmd]=entry['time']
        self.latest[direction,cmd]=entry
        self.activity.append((time.monotonic(),direction))
        if direction!='IN':return
        if cmd=='Connected':
            # The Overview describes the health of the authenticated session.
            # Keep pre-authentication failures in packet history, but do not present
            # them as current protocol issues after a successful login.
            self.errors.clear()
            self.state='Authenticated';self.expected_index=0;self.item_state='Awaiting full inventory'
            self.checked={v for v in args.get('checked_locations',[]) if type(v) is int}
            self.locations=self.checked|{v for v in args.get('missing_locations',[]) if type(v) is int}
            self.authoritative=True;self.check_revision+=1
        elif cmd=='RoomUpdate' and 'checked_locations' in args:
            self.checked.update(v for v in args['checked_locations'] if type(v) is int)
            self.check_revision+=1
        elif cmd=='ReceivedItems':
            index,items=args.get('index'),args.get('items')
            expected=self.expected_index if self.expected_index is not None else before_count
            if type(index) is not int or index<0 or not isinstance(items,(list,tuple)):
                self.issue('Malformed ReceivedItems');self.item_state='Invalid packet'
            elif index==0:
                self.expected_index=len(items);self.item_state='In sequence (full inventory received)'
                if self.resync.get('state')=='Waiting' or self.resync.get('state','').startswith('Partial'):
                    self.resync['items']='Full inventory received';self.resync['state']='Waiting'
            elif expected is None or index!=expected:
                detail=f'Item gap: expected {expected}, received {index}' if expected is None or index>expected else f'Out-of-order or duplicate items: expected {expected}, received {index}'
                self.issue(detail);self.item_state=detail
                # Do not advance the cursor on a gap. AP core owns recovery.
            else:
                self.expected_index=index+len(items);self.item_state='In sequence'
        elif cmd in {'ConnectionRefused','InvalidPacket'}:
            self.issue(cmd+': '+preview(args,500))
            if cmd=='ConnectionRefused':self.state='Login refused'
        if cmd=='Retrieved':
            nonce=args.get('wf_inspector_request')
            sent=self.probes.pop(nonce,None)
            if sent is not None:
                self.latencies.append(round((time.monotonic()-sent)*1000,1));self.latency_time=time.time()
                if nonce==self.resync.get('request'):
                    self.resync['storage']='Reply received'

    def issue(self, text):
        """Handle issue."""
        self.errors.append(dict(time=time.time(),message=sanitize(text)))

    def probe(self):
        """Handle probe."""
        self.probes={k:v for k,v in self.probes.items() if time.monotonic()-v<30}
        nonce=uuid.uuid4().hex;self.probes[nonce]=time.monotonic()
        return nonce

    def comparison(self, snapshot, revision=None, epoch=None):
        """Handle comparison."""
        rows=snapshot.get('locations',[]) if isinstance(snapshot,dict) else []
        visible={r.get('address'):r for r in rows if type(r.get('address')) is int}
        checked={ident for ident,row in visible.items() if row.get('status')=='checked'}
        pending=epoch!=self.epoch or revision!=self.check_revision
        discrepancies=[]
        for ident in sorted(self.checked-checked):
            row=visible.get(ident,{})
            discrepancies.append(dict(id=ident,name=row.get('name',str(ident)),server='Checked',wayfinder=row.get('status','Not represented')))
        for ident in sorted(checked-self.checked):
            discrepancies.append(dict(id=ident,name=visible[ident].get('name',str(ident)),server='No checked confirmation',wayfinder='Checked'))
        return dict(authoritative=self.authoritative,pending=pending,server_count=len(self.checked),wayfinder_count=len(checked),
                    total_discrepancies=len(discrepancies),discrepancies=discrepancies[:300],
                    basis='Connected baseline plus RoomUpdate deltas; Sync does not refresh this baseline')

    def summary(self):
        """Handle summary."""
        now=time.monotonic()
        recent=Counter(direction for stamp,direction in self.activity if now-stamp<=10)
        if self.resync.get('state')=='Waiting':
            if self.resync.get('items')=='Full inventory received' and self.resync.get('storage')=='Reply received':
                self.resync['state']='Server replies received'
            elif now-self.resync.get('started',now)>15:
                self.resync['state']='Partial / awaiting items (an empty inventory may not produce a Sync reply)'
        return dict(epoch=self.epoch,state=self.state,started=self.started,packets=list(self.history),latest=list(self.latest.values()),
                    counts=[dict(direction=d,command=c,count=n,last=self.last[d,c]) for (d,c),n in sorted(self.counts.items())],
                    activity=dict(inbound_10s=recent['IN'],outbound_10s=recent['OUT']),
                    items=dict(expected_index=self.expected_index,state=self.item_state),errors=list(self.errors),
                    latency_ms=self.latencies[-1] if self.latencies else None,latency_time=self.latency_time,
                    latency_basis='Get → Retrieved application round trip, including server processing',resync=dict(self.resync))
