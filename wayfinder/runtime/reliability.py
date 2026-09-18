"""Provide reliability support."""
from wayfinder.utils.ignored import ignored as _ignored
"""Runtime lifecycle and a serial, coalescing, cancellable expensive-work queue."""
import threading
import time
import uuid
from collections import OrderedDict

STATES=('OFFLINE','STARTING','READY','CONNECTING','CONNECTED','SYNCING','RECONSTRUCTING','TRACKING','DEGRADED','ERROR')
COMPONENTS=('GUI','IPC','Native Runtime','Archipelago Core','AP Server','APWorld','Logic Engine','Snapshot Pipeline','Map Engine')

class HealthState:
    """Provide health state behavior."""
    def __init__(self):
        """Handle init."""
        self.current='OFFLINE'; self.sequence=0; self.history=[]; self.components={name:{'state':'waiting','detail':'Not checked'} for name in COMPONENTS}; self.lock=threading.RLock()
    def transition(self,state,reason=''):
        """Handle transition."""
        if state not in STATES: raise ValueError('Invalid runtime state')
        with self.lock:
            previous=self.current; self.current=state
            self.sequence+=1
            transition=dict(seq=self.sequence,event_id=uuid.uuid4().hex,**{'from':previous,'to':state},reason=reason,time=time.time())
            self.history.append(transition); self.history=self.history[-64:]
            return dict(current=state,transition=transition,history=list(self.history))
    def component(self,name,state,detail):
        """Handle component."""
        if name not in COMPONENTS or state not in ('ready','waiting','busy','degraded','error','offline'): raise ValueError('Invalid component health')
        with self.lock: self.components[name]=dict(state=state,detail=detail)

class Cancelled(Exception): _ignored("intentional best-effort fallback")

class JobToken:
    """Provide job token behavior."""
    def __init__(self,key): self.key=key; self.event=threading.Event(); self.id=uuid.uuid4().hex
    def checkpoint(self):
        """Handle checkpoint."""
        if self.event.is_set(): raise Cancelled()

class RuntimeJobs:
    """Provide runtime jobs behavior."""
    def __init__(self,on_error=lambda *args:None,on_cancel=lambda *args:None):
        """Handle init."""
        self.condition=threading.Condition(); self.pending=OrderedDict(); self.active=None; self.closed=False; self.started=0.; self.on_error=on_error; self.on_cancel=on_cancel
        self.thread=threading.Thread(target=self._run,name='WayFinder-Runtime-Jobs',daemon=True); self.thread.start()
    def submit(self,key,work):
        """Handle submit."""
        token=JobToken(key)
        with self.condition:
            if self.closed: return token
            old=self.pending.pop(key,None)
            if old: old[0].event.set()
            if self.active and self.active.key==key: self.active.event.set()
            if len(self.pending)>=16:
                _,(old,_)=self.pending.popitem(last=False); old.event.set()
            self.pending[key]=(token,work); self.condition.notify()
        return token
    def cancel(self):
        """Handle cancel."""
        with self.condition:
            if self.active: self.active.event.set()
            for token,_ in self.pending.values(): token.event.set()
            self.pending.clear()
    def status(self):
        """Handle status."""
        with self.condition: return dict(busy=self.active is not None,job=self.active.key if self.active else '',job_id=self.active.id if self.active else '',busy_seconds=time.monotonic()-self.started if self.active else 0,queued=len(self.pending))
    def close(self):
        """Handle close."""
        with self.condition: self.cancel(); self.closed=True; self.condition.notify()
    def _run(self):
        """Handle run."""
        while True:
            with self.condition:
                self.condition.wait_for(lambda:self.closed or self.pending)
                if self.closed:return
                _,(token,work)=self.pending.popitem(last=False); self.active=token; self.started=time.monotonic()
            try: token.checkpoint(); work(token)
            except Cancelled: self.on_cancel(token)
            except BaseException as exc: self.on_error(token,exc)
            finally:
                with self.condition: self.active=None
