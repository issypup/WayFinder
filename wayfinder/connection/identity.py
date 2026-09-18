"""Seed-scoped identity and snapshot validation shared by runtime and GUI."""
import hashlib
import json
import sys
from pathlib import Path
from functools import lru_cache
from urllib.parse import urlsplit

IDENTITY_FIELDS=('server','seed','slot','slot_name','team','game','apworld_version','slot_data_fingerprint')

def normal_server(value):
    """Handle normal server."""
    parts=urlsplit(value if '://' in value else 'ws://'+value)
    host=(parts.hostname or '').lower()
    if ':' in host: host='['+host+']'
    return host+(':'+str(parts.port) if parts.port else ':38281')

def fingerprint(value):
    """Handle fingerprint."""
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False).encode()).hexdigest()

@lru_cache(maxsize=128)
def _source_version(path,mtime,size):
    """Handle source version."""
    with open(path,'rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def world_version(world):
    """Handle world version."""
    if world is None:return 'unknown'
    if getattr(world,'_wayfinder_source_hash',''):
        return str(getattr(world,'_wayfinder_manifest_version','') or getattr(world,'world_version','unversioned'))+' / sha256:'+world._wayfinder_source_hash
    version=getattr(world,'world_version',None) or getattr(world,'data_version',None) or getattr(world,'required_client_version',None) or 'unknown'
    module=sys.modules.get(type(world).__module__)
    source=str(getattr(module,'__file__','') or '')
    if '.apworld' in source.lower():source=source[:source.lower().index('.apworld')+len('.apworld')]
    try:
        path=Path(source);stat=path.stat()
        return str(version)+' / sha256:'+_source_version(str(path),stat.st_mtime_ns,stat.st_size)
    except (OSError,ValueError):return str(version)

def seed_identity(ctx, world=None):
    """Handle seed identity."""
    version=world_version(world)
    identity=dict(server=normal_server(str(getattr(ctx,'server_address','') or '')),seed=str(getattr(ctx,'seed_name','') or ''),slot=getattr(ctx,'slot',None),slot_name=str(getattr(ctx,'auth','') or ''),team=getattr(ctx,'team',None),game=str(getattr(ctx,'game','') or ''),apworld_version=str(version),slot_data_fingerprint=fingerprint(getattr(ctx,'slot_data',{}) or {}))
    identity['id']=fingerprint(identity)
    identity['complete']=all(identity[k] not in ('',None,'unknown') for k in IDENTITY_FIELDS)
    return identity

def validate_identity(identity):
    """Return validate identity."""
    if not isinstance(identity,dict) or any(k not in identity for k in IDENTITY_FIELDS):
        raise ValueError('Incomplete seed identity')
    complete=all(identity[k] not in ('',None,'unknown') for k in IDENTITY_FIELDS)
    if identity.get('complete') is not complete:raise ValueError('Invalid identity completeness flag')
    if identity.get('id') != fingerprint({k:identity[k] for k in IDENTITY_FIELDS}):
        raise ValueError('Seed identity digest mismatch')
    return identity

def validate_snapshot(data, strict=False):
    """Return validate snapshot."""
    if not isinstance(data,dict): raise ValueError('Snapshot must be an object')
    if not isinstance(data.get('connected',False),bool): raise ValueError('Invalid connection flag')
    for key in ('snapshot_sequence','refresh_id','team'):
        value=data.get(key,0)
        if type(value) is not int or value < 0: raise ValueError('Invalid '+key)
    for key in ('server','slot_name','game','runtime_id'):
        if not isinstance(data.get(key,''),str): raise ValueError('Invalid '+key)
    for key in ('locations','inventory','entrances','entrance_details','hints','events'):
        if not isinstance(data.get(key,[]),list): raise ValueError('Invalid '+key)
    for key in ('hints','entrance_details'):
        if any(not isinstance(row,dict) for row in data.get(key,[])):raise ValueError('Invalid '+key+' entry')
    for hint in data.get('hints',[]):
        if type(hint.get('item_flags',0)) is not int:raise ValueError('Invalid hint flags')
    for key in ('rule_details','goal_detail','compatibility','area_summary'):
        if not isinstance(data.get(key,{}),dict):raise ValueError('Invalid '+key)
    if any(not isinstance(row,dict) for row in data.get('rule_details',{}).values()):raise ValueError('Invalid rule detail')
    names=set()
    for row in data.get('locations',[]):
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or not row['name'] or row['name'] in names: raise ValueError('Invalid or duplicate location')
        names.add(row['name'])
        if row.get('status') not in {'reachable','glitched','out_of_logic','checked','ignored','unknown'}: raise ValueError('Invalid location status')
    for row in data.get('inventory',[]):
        if not isinstance(row,dict) or not isinstance(row.get('name'),str) or type(row.get('count',0)) is not int or row.get('count',0)<0: raise ValueError('Invalid inventory')
    if strict:
        identity=validate_identity(data.get('seed_identity'))
        if normal_server(data.get('server',''))!=identity['server'] or data.get('slot_name','')!=identity['slot_name'] or data.get('game','')!=identity['game'] or data.get('team',0)!=int(identity['team'] or 0): raise ValueError('Snapshot identity fields disagree')
        if data.get('snapshot_sequence',0)<=0 or not data.get('runtime_id'): raise ValueError('Missing snapshot generation')
    return data

class SnapshotGate:
    """Provide snapshot gate behavior."""
    def __init__(self):
        """Handle init."""
        self.connection_id=''; self.expected_seed=''; self.sequences={}; self.target=None
    def begin(self,connection_id,server='',slot=''):
        """Handle begin."""
        self.connection_id=connection_id; self.expected_seed=''; self.sequences={}; self.target=(normal_server(server),slot) if server else None
    def announce(self,identity,connection_id):
        """Handle announce."""
        validate_identity(identity)
        if connection_id!=self.connection_id: return False
        if self.target and (identity['server'],identity['slot_name'])!=self.target: return False
        if self.expected_seed and self.expected_seed!=identity['id']:return False
        self.expected_seed=identity['id']; return True
    def check(self,data):
        """Handle check."""
        validate_snapshot(data,True)
        if data.get('connection_id')!=self.connection_id: raise ValueError('Obsolete connection snapshot')
        identity=data['seed_identity']
        if data.get('connected') and (not self.expected_seed or identity['id']!=self.expected_seed): raise ValueError('Snapshot from an unconfirmed seed')
        if data.get('connected') and self.target and (identity['server'],identity['slot_name'])!=self.target: raise ValueError('Snapshot target mismatch')
        if data['snapshot_sequence']<=self.sequences.get(data['runtime_id'],0): raise ValueError('Obsolete snapshot generation')
    def commit(self,data): self.sequences[data['runtime_id']]=data['snapshot_sequence']
