# /**
#  * Module: wayfinder.app/protocol.py
#  * Purpose: GUI module for protocol; presents or coordinates WayFinder state without owning the underlying game logic.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

"""Shared WayFinder IPC protocol model (GUI and injected runtime)."""
from __future__ import annotations
import base64, json, zlib, time
# Constant(s): `PROTOCOL_VERSION`; shared configuration value(s) intentionally kept stable within this module.
PROTOCOL_VERSION=3
# Constant(s): `PROTOCOL_MIN`; shared configuration value(s) intentionally kept stable within this module.
PROTOCOL_MIN=2
# Constant(s): `PROTOCOL_MAX`; shared configuration value(s) intentionally kept stable within this module.
PROTOCOL_MAX=3
# Constant(s): `LEGACY_PROTOCOLS`; shared configuration value(s) intentionally kept stable within this module.
LEGACY_PROTOCOLS=(2,)
# Constant(s): `MAX_MESSAGE_BYTES`; shared configuration value(s) intentionally kept stable within this module.
MAX_MESSAGE_BYTES=2*1024*1024
# Constant(s): `SNAPSHOT_COMPRESS_THRESHOLD`; shared configuration value(s) intentionally kept stable within this module.
SNAPSHOT_COMPRESS_THRESHOLD=128*1024
# Constant(s): `CAPABILITIES`; shared configuration value(s) intentionally kept stable within this module.
CAPABILITIES=("request_ids","heartbeat","structured_errors","snapshot_zlib","priority_messages","capability_health","version_matrix","seed_identity","runtime_health","event_ids","job_cancellation")
# Constant(s): `ERROR_CODES`; shared configuration value(s) intentionally kept stable within this module.
ERROR_CODES={"bad_command":"WF_IPC_BAD_COMMAND","bad_protocol":"WF_IPC_BAD_PROTOCOL","stale_session":"WF_IPC_STALE_SESSION","message_too_large":"WF_IPC_TOO_LARGE","bad_request":"WF_IPC_BAD_REQUEST","runtime_failure":"WF_IPC_RUNTIME_FAILURE"}
# /**
#  * Function: request_id
#  * Purpose: Perform the request id operation while keeping the surrounding subsystem state consistent.
#  * @param value: Value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def request_id(value):
    """Handle request id."""
    try: return max(0,int(value or 0))
    except (TypeError,ValueError): return 0
# /**
#  * Function: error_payload
#  * Purpose: Perform the error payload operation while keeping the surrounding subsystem state consistent.
#  * @param code: Code supplied by the caller; see type hints and call sites for domain constraints.
#  * @param message: Message supplied by the caller; see type hints and call sites for domain constraints.
#  * @param request_id_value: Request id value supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def error_payload(code,message,request_id_value=0):
    """Handle error payload."""
    return {"type":"error","error_code":ERROR_CODES.get(code,code),"message":str(message),"request_id":request_id(request_id_value),"priority":"high"}
# /**
#  * Function: encode_snapshot
#  * Purpose: Perform the encode snapshot operation while keeping the surrounding subsystem state consistent.
#  * @param data: Data supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def encode_snapshot(data):
    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
    """Handle encode snapshot."""
    raw=json.dumps(data,separators=(",",":"),ensure_ascii=False).encode("utf-8")
    if len(raw)<SNAPSHOT_COMPRESS_THRESHOLD: return {"type":"snapshot","data":data,"encoding":"json","priority":"bulk"}
    # Variable(s): `packed` (packed); named state retained for the surrounding calculation or subsequent calls.
    packed=base64.b64encode(zlib.compress(raw,6)).decode("ascii")
    return {"type":"snapshot","data":packed,"encoding":"zlib+base64","uncompressed_bytes":len(raw),"priority":"bulk"}
# /**
#  * Function: decode_snapshot
#  * Purpose: Perform the decode snapshot operation while keeping the surrounding subsystem state consistent.
#  * @param msg: Message supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def decode_snapshot(msg):
    """Handle decode snapshot."""
    if msg.get("encoding")!="zlib+base64": return msg.get("data")
    # Variable(s): `raw` (raw value); named state retained for the surrounding calculation or subsequent calls.
    limit=64*1024*1024
    decoder=zlib.decompressobj()
    raw=decoder.decompress(base64.b64decode(msg.get("data","").encode("ascii"),validate=True),limit+1)
    if len(raw)>limit or decoder.unconsumed_tail or not decoder.eof: raise ValueError("Invalid or oversized compressed snapshot")
    return json.loads(raw.decode("utf-8"))
