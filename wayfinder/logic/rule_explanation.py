"""Bounded, non-executing explanations of APWorld Python rules.

The callable's actual execution remains authoritative. Unknown AST constructs are
explicit holes, never guessed requirements. In particular, exploring an OR branch
does not call an APWorld helper a second time or mutate its world.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
import zipfile
import functools
from functools import lru_cache

_STATE = object()
_MISSING = object()


@lru_cache(maxsize=2048)
def _source(code):
    """Handle source."""
    try:
        lines, start = inspect.getsourcelines(code)
    except (OSError, TypeError, IOError):
        # zipimport code filenames point inside the .apworld archive.
        filename = code.co_filename.replace('\\', '/')
        cut = filename.lower().find('.apworld/')
        if cut < 0:
            raise ValueError('Python source is unavailable (generated or compiled callable).')
        with zipfile.ZipFile(filename[:cut + 8]) as archive:
            lines = archive.read(filename[cut + 9:]).decode('utf-8-sig').splitlines(True)
        start = 1
    tree = ast.parse(textwrap.dedent(''.join(lines)))
    expected = code.co_firstlineno - start + 1
    candidates = [n for n in ast.walk(tree)
                  if isinstance(n, (ast.Lambda, ast.FunctionDef))
                  and n.lineno <= expected <= getattr(n, 'end_lineno', n.lineno)
                  and (isinstance(n, ast.Lambda) if code.co_name == '<lambda>' else getattr(n, 'name', '') == code.co_name)]
    if len(candidates) != 1:
        raise ValueError('Source is ambiguous: multiple rules share this source line.')
    return candidates[0], start - 1


def walk(node):
    """Handle walk."""
    yield node
    for child in node.get('children', []):
        yield from walk(child)


def _node(kind, label='', satisfied=None, **fields):
    """Handle node."""
    return dict(kind=kind, label=label or kind, satisfied=satisfied, **fields)


def _combine(kind, children, **fields):
    """Handle combine."""
    flattened = []
    for child in children:
        if child['kind'] == kind and not child.get('helper') and not child.get('negated'):
            flattened.extend(child.get('children', []))
        else:
            flattened.append(child)
    values = [x['satisfied'] for x in flattened]
    value = (False if False in values else None if None in values else True) if kind == 'ALL' else (True if True in values else None if None in values else False)
    return _node(kind, satisfied=value, children=flattened, **fields)


class Analyzer:
    """Provide analyzer behavior."""
    def __init__(self, player, inventory, regions, events, groups):
        """Handle init."""
        self.player, self.inventory, self.regions = player, inventory, regions
        self.events, self.groups = events, groups
        self.stack = []
        self.budget = 512

    def unknown(self, reason, **fields):
        """Handle unknown."""
        return _node('UNKNOWN', 'Unresolved Python rule', reason=reason, **fields)

    def value(self, node, env):
        """Handle value."""
        if isinstance(node, ast.Name):
            return env.get(node.id, _MISSING)
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
            number = self.value(node.operand, env)
            return -number if type(number) is int else _MISSING
        if isinstance(node, ast.BinOp):
            left, right = self.value(node.left, env), self.value(node.right, env)
            if type(left) is int and type(right) is int and max(left.bit_length(), right.bit_length()) <= 64:
                if isinstance(node.op, ast.Add): return left + right
                if isinstance(node.op, ast.Sub): return left - right
                if isinstance(node.op, ast.Mult): return left * right
        if isinstance(node, ast.Dict):
            pairs = [(self.value(k, env), self.value(v, env)) for k, v in zip(node.keys, node.values)]
            if all(type(k) is str and type(v) is int for k, v in pairs):
                return dict(pairs)
            return _MISSING
        if isinstance(node, (ast.Tuple, ast.List, ast.Set)):
            values = [self.value(x, env) for x in node.elts]
            return values if all(x is not _MISSING for x in values) else _MISSING
        if isinstance(node, ast.Attribute):
            owner = self.value(node.value, env)
            if owner is _MISSING or owner is _STATE:
                return _MISSING
            # Never invoke a property, descriptor or dynamic __getattr__.
            value = inspect.getattr_static(owner, node.attr, _MISSING)
            if inspect.isfunction(value) and not inspect.isclass(owner):
                return value.__get__(owner, type(owner))
            if isinstance(value, (property, staticmethod, classmethod)):
                return _MISSING
            return value
        return _MISSING

    def function(self, fn, args, kwargs=None):
        """Handle function."""
        if isinstance(fn, functools.partial):
            return self.function(fn.func, [*fn.args, *args], dict(fn.keywords or {}, **(kwargs or {})))
        if type(fn).__module__ == 'rule_builder.rules':
            return self.resolved(fn)
        if not (inspect.isfunction(fn) or inspect.ismethod(fn)):
            return self.unknown('Helper has no inspectable Python function body.')
        code = fn.__code__
        origin = {'file': code.co_filename, 'line': code.co_firstlineno,
                  'function': fn.__qualname__}
        if code in self.stack:
            return self.unknown('Recursive helper cycle: ' + fn.__qualname__, source=origin)
        if len(self.stack) >= 16 or self.budget <= 0:
            return self.unknown('Explanation limit reached (helper depth or node budget).', source=origin)
        try:
            node, offset = _source(code)
            bound = inspect.signature(fn, follow_wrapped=False).bind(*args, **(kwargs or {}))
            bound.apply_defaults()
            closure = inspect.getclosurevars(fn)
            env = dict(closure.globals, **closure.nonlocals, **bound.arguments)
            if inspect.ismethod(fn):
                env[code.co_varnames[0]] = fn.__self__
            body = node.body if isinstance(node, ast.Lambda) else [x for x in node.body if not (isinstance(x, ast.Expr) and isinstance(x.value, ast.Constant) and isinstance(x.value.value, str))]
            if isinstance(body, list):
                if len(body) != 1 or not isinstance(body[0], ast.Return):
                    return self.unknown('Helper uses statements/control flow that cannot be normalized safely; see executed helper trace.', source=origin)
                body = body[0].value
            self.stack.append(code)
            try:
                result = self.expression(body, env, code.co_filename, offset)
            finally:
                self.stack.pop()
            result.setdefault('source', origin)
            return result
        except Exception as exc:
            return self.unknown(f'Source/helper resolution unavailable: {type(exc).__name__}: {exc}', source=origin)

    def resolved(self, rule):
        """Read AP core's resolved rule data without running its explain hooks."""
        token = ('resolved', id(rule))
        if token in self.stack or len(self.stack) >= 16 or self.budget <= 0:
            return self.unknown('Recursive resolved rule or explanation limit reached.')
        self.budget -= 1
        self.stack.append(token)
        get = lambda name, default=None: inspect.getattr_static(rule, name, default)
        evaluator = inspect.getattr_static(type(rule), '_evaluate', None)
        code = getattr(evaluator, '__code__', None)
        source = {'file': code.co_filename, 'line': code.co_firstlineno} if code else {}
        name = type(rule).__qualname__.removesuffix('.Resolved')
        try:
            if get('player') != self.player:
                return self.unknown('Resolved rule refers to another player.', source=source)
            if name in {'True_', 'False_'}:
                return _combine('ALL' if name == 'True_' else 'ANY', [], source=source)
            if name in {'And', 'Or'}:
                children = get('children', ())
                if type(children) not in (tuple, list) or len(children) > 256:
                    return self.unknown('Resolved child collection is unsupported.', source=source)
                return _combine('ALL' if name == 'And' else 'ANY', [self.function(x, [_STATE]) for x in children], source=source)
            if name == 'Has':
                return self.predicate('has', [get('item_name'), self.player, get('count', 1)], {}, source)
            if name in {'HasAll', 'HasAny'}:
                return self.predicate('has_all' if name == 'HasAll' else 'has_any', [get('item_names'), self.player], {}, source)
            if name in {'HasAllCounts', 'HasAnyCount'}:
                pairs = get('item_counts', ())
                if type(pairs) is not tuple or len(pairs) > 256 or not all(type(p) is tuple and len(p) == 2 and type(p[0]) is str and type(p[1]) is int for p in pairs):
                    return self.unknown('Resolved item/count pairs are unsupported.', source=source)
                return _combine('ALL' if name == 'HasAllCounts' else 'ANY', [self.item(k, v, source) for k, v in pairs], source=source)
            if name in {'HasGroup', 'HasGroupUnique', 'HasFromList', 'HasFromListUnique'}:
                return self.predicate('has_from_list_unique' if name.endswith('Unique') else 'has_from_list', [get('item_names'), self.player, get('count', 1)], {}, source)
            if name == 'CanReachRegion':
                return self.predicate('can_reach_region', [get('region_name'), self.player], {}, source)
            return self.unknown('Unsupported resolved rule: ' + name, source=source)
        except Exception as exc:
            return self.unknown(f'Resolved rule data unavailable: {type(exc).__name__}: {exc}', source=source)
        finally:
            self.stack.pop()

    def expression(self, node, env, filename, offset):
        """Handle expression."""
        self.budget -= 1
        source = {'file': filename, 'line': getattr(node, 'lineno', 1) + offset}
        if self.budget < 0:
            return self.unknown('Explanation node budget reached.', source=source)
        if isinstance(node, ast.BoolOp):
            return _combine('ALL' if isinstance(node.op, ast.And) else 'ANY',
                            [self.expression(x, env, filename, offset) for x in node.values], source=source)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
            child = self.expression(node.operand, env, filename, offset)
            return negate(child)
        value = self.value(node, env)
        if type(value) is bool:
            return _combine('ALL' if value else 'ANY', [], source=source)
        if isinstance(node, ast.Call):
            args = [self.value(x, env) for x in node.args]
            kwargs = {x.arg: self.value(x.value, env) for x in node.keywords if x.arg}
            if any(x is _MISSING for x in args + list(kwargs.values())) or any(x.arg is None for x in node.keywords):
                return self.unknown('Helper arguments use unsupported dynamic expressions.', source=source)
            if isinstance(node.func, ast.Attribute) and self.value(node.func.value, env) is _STATE:
                return self.predicate(node.func.attr, args, kwargs, source)
            fn = self.value(node.func, env)
            if fn is _MISSING:
                return self.unknown('Unresolvable helper: ' + ast.unparse(node.func), source=source)
            child = self.function(fn, args, kwargs)
            child['helper'] = getattr(fn, '__qualname__', ast.unparse(node.func))
            return child
        if isinstance(node, ast.Compare) and len(node.ops) == 1:
            call = node.left
            # APWorlds also read CollectionState.prog_items directly.
            if isinstance(call, ast.Subscript) and isinstance(call.value, ast.Subscript):
                base = call.value.value
                name = self.value(call.slice, env)
                player = self.value(call.value.slice, env)
                required = self.value(node.comparators[0], env)
                if isinstance(base, ast.Attribute) and base.attr == 'prog_items' and self.value(base.value, env) is _STATE and type(player) is int and player == self.player and isinstance(name, str) and type(required) is int:
                    op = {ast.GtE: '>=', ast.Gt: '>', ast.LtE: '<=', ast.Lt: '<', ast.Eq: '==', ast.NotEq: '!='}.get(type(node.ops[0]))
                    if op:
                        have = self.inventory.get(name, 0)
                        return _node('COUNT', name, compare(have, op, required), have=have, required=required, operator=op, source=source)
            if isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and self.value(call.func.value, env) is _STATE and call.func.attr == 'count':
                args = [self.value(x, env) for x in call.args]
                required = self.value(node.comparators[0], env)
                if len(args) == 2 and isinstance(args[0], str) and args[1] == self.player and type(required) is int and not call.keywords:
                    op = {ast.GtE: '>=', ast.Gt: '>', ast.LtE: '<=', ast.Lt: '<', ast.Eq: '==', ast.NotEq: '!='}.get(type(node.ops[0]))
                    if op:
                        have = self.inventory.get(args[0], 0)
                        return _node('COUNT', args[0], compare(have, op, required), have=have, required=required, operator=op, source=source)
        return self.unknown('Unsupported Python expression: ' + type(node).__name__, source=source)

    def predicate(self, method, args, kwargs, source):
        # Bind only the documented state predicates, never call the state here.
        """Handle predicate."""
        names = {'has': ('item', 'player', 'count'), 'has_all': ('items', 'player'),
                 'has_any': ('items', 'player'), 'has_group': ('group', 'player', 'count'),
                 'has_all_counts': ('items', 'player'), 'has_group_unique': ('group', 'player', 'count'),
                 'has_from_list': ('items', 'player', 'count'), 'has_from_list_unique': ('items', 'player', 'count'),
                 'can_reach_region': ('region', 'player'), 'can_reach': ('spot', 'resolution_hint', 'player')}
        if method not in names:
            return self.unknown('Unresolvable CollectionState helper: ' + method, source=source)
        params = names[method]
        if len(args) > len(params) or any(k not in params for k in kwargs) or any(k in params[:len(args)] for k in kwargs):
            return self.unknown('Unsupported predicate arguments: ' + method, source=source)
        values = dict(zip(params, args)); values.update(kwargs)
        if values.get('player', self.player) not in (None, self.player):
            return self.unknown('Remote player state is unavailable to this local explanation.', source=source)
        if method == 'has_all_counts':
            items = values.get('items')
            if type(items) is dict and len(items) <= 256 and all(type(k) is str and type(v) is int for k, v in items.items()):
                return _combine('ALL', [self.item(k, v, source) for k, v in items.items()], source=source)
            return self.unknown('Dynamic item/count mapping.', source=source)
        if method in {'has_group_unique', 'has_from_list', 'has_from_list_unique'}:
            group = values.get('group')
            items = self.groups.get(group) if isinstance(group, str) else values.get('items')
            required = values.get('count', 1)
            if not isinstance(items, (list, tuple, set, frozenset)) or len(items) > 256 or not all(type(x) is str for x in items) or type(required) is not int:
                return self.unknown('Dynamic item list or unknown group.', source=source)
            unique = method.endswith('_unique')
            have = sum(int(self.inventory.get(x, 0) >= 1) if unique else self.inventory.get(x, 0) for x in items)
            return _node('COUNT', group or 'Items from list', have >= required, have=have, required=required, operator='>=', items=sorted(items), unique=unique, source=source)
        if method in {'can_reach', 'can_reach_region'}:
            name = values.get('spot', values.get('region'))
            if not isinstance(name, str) or values.get('resolution_hint', 'Region') not in (None, 'Region'):
                return self.unknown('Location/entrance reachability requires the executed graph trace.', source=source)
            return _node('REGION', name, name in self.regions, source=source)
        if method in {'has_all', 'has_any', 'has_group'}:
            items = values.get('items')
            if method == 'has_group':
                group = values.get('group')
                if not isinstance(group, str) or group not in self.groups:
                    return self.unknown('Unknown item group.', source=source)
                items = sorted(self.groups[group])
                required = values.get('count', 1)
                if type(required) is not int:
                    return self.unknown('Non-integer group count.', source=source)
                have = sum(self.inventory.get(x, 0) for x in items)
                return _node('COUNT', group, have >= required, have=have, required=required, operator='>=', items=items, source=source)
            if not isinstance(items, (list, tuple, set, frozenset)) or not all(isinstance(x, str) for x in items) or len(items) > 256:
                return self.unknown('Item collection is dynamic or too large.', source=source)
            return _combine('ALL' if method == 'has_all' else 'ANY', [self.item(x, 1, source) for x in sorted(items)], source=source)
        name, count = values.get('item'), values.get('count', 1)
        if not isinstance(name, str) or type(count) is not int:
            return self.unknown('Item name/count is not a literal value.', source=source)
        return self.item(name, count, source)

    def item(self, name, count, source):
        """Handle item."""
        have = self.inventory.get(name, 0)
        return _node('EVENT' if name in self.events else 'ITEM' if count == 1 else 'COUNT', name,
                     have >= count, have=have, required=count, operator='>=', source=source)


def compare(have, op, required):
    """Handle compare."""
    return {'>=': have >= required, '>': have > required, '<=': have <= required,
            '<': have < required, '==': have == required, '!=': have != required}[op]


def negate(node):
    """Handle negate."""
    if node['kind'] in {'ALL', 'ANY'}:
        return _combine('ANY' if node['kind'] == 'ALL' else 'ALL', [negate(x) for x in node.get('children', [])], source=node.get('source', {}))
    result = dict(node)
    result['satisfied'] = None if node['satisfied'] is None else not node['satisfied']
    if 'operator' in node:
        result['operator'] = {'>=': '<', '>': '<=', '<=': '>', '<': '>=', '==': '!=', '!=': '=='}[node['operator']]
    else:
        result['negated'] = not node.get('negated', False)
    return result


def impossible(node):
    """Prove local contradictions only; an item shortage is never impossible."""
    children = node.get('children', [])
    if node['kind'] == 'ANY':
        return not children or all(impossible(c) for c in children)
    if node['kind'] in {'ITEM', 'COUNT', 'EVENT'}:
        return impossible(_combine('ALL', [node]))
    if node['kind'] != 'ALL':
        return False
    if any(impossible(c) for c in children if c['kind'] in {'ALL', 'ANY'}):
        return True
    bounds = {}
    regions = {}
    for child in children:
        if child['kind'] == 'REGION':
            name, negative = child['label'], bool(child.get('negated'))
            if name in regions and regions[name] != negative: return True
            regions[name] = negative
        if child['kind'] not in {'ITEM', 'COUNT', 'EVENT'} or child.get('items'):
            continue
        key = child['label']; low, high, excluded = bounds.setdefault(key, [0, float('inf'), set()])
        n, op = child.get('required', 1), child.get('operator', '>=')
        if op == '>=': low = max(low, n)
        elif op == '>': low = max(low, n + 1)
        elif op == '<=': high = min(high, n)
        elif op == '<': high = min(high, n - 1)
        elif op == '==': low, high = max(low, n), min(high, n)
        elif op == '!=': excluded.add(n)
        bounds[key] = [low, high, excluded]
        if low > high or low == high and low in excluded:
            return True
    return False


def annotate_events(details, event_names):
    """Classify unswept event requirements from the generated event producers."""
    for detail in details:
        trees = [detail.get('normalized_rule') or {}]
        trees.extend(b for group in detail.get('alternative_branches', []) for b in group['branches'])
        for tree in trees:
            for node in walk(tree):
                if node.get('kind') == 'ITEM' and node.get('label') in event_names:
                    node['kind'] = 'EVENT'


def uncertain_regions(reachable, entrances):
    """Propagate failures through potentially open edges, never known blockers."""
    known = set(reachable)
    uncertain = {}
    changed = True
    while changed:
        changed = False
        for edge in entrances:
            source, target = edge.get('source_region'), edge.get('target_region')
            if not target or target in known or target in uncertain or source not in known | uncertain.keys():
                continue
            if edge.get('error') or edge.get('satisfied'):
                if edge.get('error') or source in uncertain:
                    uncertain[target] = ('Parent-region logic is unknown: entrance ' + str(edge.get('name', '')) + ': ' + str(edge['error'])) if edge.get('error') else uncertain[source]
                    changed = True
    return uncertain


def display_tree(detail):
    """Adapt canonical trees to the existing Path Explorer node vocabulary."""
    kinds = {'ALL': 'and', 'ANY': 'or', 'ITEM': 'item', 'COUNT': 'item_count',
             'EVENT': 'event', 'REGION': 'region', 'UNKNOWN': 'opaque'}
    def convert(node):
        """Handle convert."""
        source = node.get('source', {})
        origin = f"{source.get('file', '')}:{source.get('line', 0)}" if source else ''
        result = dict(node, kind=kinds.get(node['kind'], 'opaque'),
                      detail=' — '.join(x for x in (node.get('reason', ''), node.get('helper', ''), origin) if x),
                      children=[convert(x) for x in node.get('children', [])])
        if node.get('negated'): result['label'] = 'NOT ' + node['label']
        return result
    tree = convert(detail['normalized_rule'])
    # Explanation holes must not change the root's actually executed result.
    tree['satisfied'] = None if detail.get('error') else detail.get('satisfied')
    if detail.get('error'): tree['detail'] = 'Logic evaluation failed: ' + detail['error']
    return tree


def explain(rule, *, player, inventory, reachable_regions, events, groups):
    """Handle explain."""
    tree = Analyzer(player, inventory, reachable_regions, events, groups).function(rule, [_STATE]) if callable(rule) else _combine('ALL', [])
    reasons = list(dict.fromkeys(n['reason'] for n in walk(tree) if n.get('reason')))
    return {'normalized_rule': tree, 'explanation_complete': not reasons,
            'explanation_unknown_reasons': reasons, 'impossible_rule': impossible(tree),
            'alternative_branches': [dict(source=n.get('source', {}), branches=n['children']) for n in walk(tree) if n['kind'] == 'ANY' and n.get('children')]}


def explanation_lines(detail):
    """Shared wording for location, entrance, event and goal dialogs."""
    from wayfinder.diagnostics import sanitize
    lines = []
    error = detail.get('error')
    if error:
        lines.append('Logic evaluation failed: ' + str(error))
        lines.append('This is a logic failure; it does not identify a non-progression check.')
    if detail.get('impossible_rule'):
        lines.append('Impossible local rule: a constant-false branch or contradictory requirements were proven.')
    reasons = detail.get('explanation_unknown_reasons', [])
    if reasons:
        lines.append('Explanation incomplete (the executed rule result remains authoritative):')
        lines.extend('  • ' + str(x) for x in reasons)
    tree = detail.get('normalized_rule')
    if tree:
        lines.append('\nNormalized local rule — ANY children are alternative branches:')
        def render(node, depth=0):
            """Handle render."""
            state = 'satisfied' if node.get('satisfied') is True else 'blocked' if node.get('satisfied') is False else 'unknown'
            label = node.get('label', '')
            quantity = f" {node.get('operator', '>=')} {node['required']} (have {node.get('have', '?')})" if 'required' in node else ''
            lines.append('  ' * depth + f"{node['kind']} {'NOT ' if node.get('negated') else ''}{label}{quantity}: {state}")
            source = node.get('source', {})
            if source.get('file'):
                lines.append('  ' * (depth + 1) + f"{node.get('helper', source.get('function', ''))} — {source['file']}:{source.get('line', 0)}")
            for child in node.get('children', []): render(child, depth + 1)
        render(tree)
    if detail.get('helper_trace'):
        lines.append('\nExecuted functions (actual returns, in call order):')
        for row in detail['helper_trace']:
            result = row.get('result')
            state = 'true' if result is True else 'false' if result is False else 'no boolean return / raised'
            lines.append(f"  {row['name']}: {state} — {row['file']}:{row['line']}")
    return sanitize(lines)
