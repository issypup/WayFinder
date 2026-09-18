"""Shared, stdlib-only diagnostic records and secret redaction."""

# sig:kuro:pluralchat

import re
from datetime import datetime

CATEGORIES = ('RUNTIME', 'AP', 'LOGIC', 'MAP', 'APWORLD', 'DEPENDENCY', 'SNAPSHOT', 'GUI')
_SECRET_KEY = re.compile(r'(?i)(?:password|passwd|pwd|token|secret|api[_-]?key|authorization|cookie)')
_ASSIGNMENT = re.compile(r'''(?ix)(["']?(?:[\w-]*(?:password|passwd|token|secret|api[_-]?key)|pwd|authorization|cookie)["']?\s*[:=]\s*)("(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|[^\s,;&}\]]+)''')
_AUTH = re.compile(r'(?i)\b(Bearer|Basic)\s+[^\s,;"\']+')
_COMMAND = re.compile(r'(?im)((?:/|!)(?:password|token|login)\s+)[^\r\n]+')
_URL = re.compile(r'(?i)(\b[a-z][a-z0-9+.-]*://)[^\s/@]+:[^\s/@]*@')
_KNOWN = set()

def register_secret(value):
    """Handle register secret."""
    if value:
        _KNOWN.add(str(value))

def sanitize(value):
    """Redact nested credentials and common free-text/URL/command forms."""
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if _SECRET_KEY.search(str(k)) else sanitize(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [sanitize(v) for v in value]
    if not isinstance(value, str):
        return value
    for secret in sorted(_KNOWN, key=len, reverse=True):
        value = value.replace(secret, '[REDACTED]')
    value = _AUTH.sub(r'\1 [REDACTED]', value)
    value = _ASSIGNMENT.sub(r'\1[REDACTED]', value)
    value = re.sub(r"(?i)(--(?:password|token|api-key|secret)\s+)\S+", r"\1[REDACTED]", value)
    value = _COMMAND.sub(r'\1[REDACTED]', value)
    return _URL.sub(r'\1[REDACTED]@', value)

def category_for(message):
    """Handle category for."""
    text = str(message).lower()
    for category, words in (
        ('APWORLD', ('apworld', 'world_loader', 'worldloader', 'world build')),
        ('DEPENDENCY', ('dependency', 'dependencies', 'pip ', 'installer')),
        ('SNAPSHOT', ('snapshot',)), ('MAP', ('map', 'pack', 'marker')),
        ('LOGIC', ('logic', 'solver', 'reachability', 'rule')),
        ('AP', ('archipelago', 'command', 'server', 'socket', 'connected', 'connection')),
        ('RUNTIME', ('runtime', 'startup', 'transport', 'boot'))):
        if any(word in text for word in words):
            return category
    return 'GUI'

def make_record(message, category=None, level=None):
    """Return make record."""
    message = str(sanitize(str(message))).rstrip()
    category = category or category_for(message)
    if category not in CATEGORIES:
        raise ValueError('Unknown log category: ' + category)
    if level is None:
        if re.search(r'(?i)\b(error|exception|traceback|failed|failure|crashed)\b', message):
            level = 'ERROR'
        elif re.search(r'(?i)\b(warning|warn|stale|timeout)\b', message):
            level = 'WARNING'
        else:
            level = 'INFO'
    return dict(timestamp=datetime.now().astimezone().isoformat(timespec='seconds'), category=category, level=level, message=message)

def format_record(record):
    """Return format record."""
    return f"[{record['timestamp']}] [{record['category']}] [{record['level']}] {record['message']}"
