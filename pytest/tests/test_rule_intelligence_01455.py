"""Provide test rule intelligence 01455 support."""
from collections import Counter
from types import SimpleNamespace
import importlib.util
import sys
import zipfile

from wayfinder.logic.apworld_adapter import trace_access_rule
from wayfinder.logic.rule_explanation import explain, walk, uncertain_regions, display_tree, explanation_lines


def trace(rule, items=None, events=None):
    """Handle trace."""
    return trace_access_rule(SimpleNamespace(access_rule=rule), player=1,
                             inventory=Counter(items or {}), reachable_regions={'Menu'},
                             events=set(events or ()), groups={'Keys': {'Red', 'Blue'}}, multiworld=None)


def helper(state, item='Key'):
    """Handle helper."""
    return state.has(item, 1)


def recursive(state):
    """Handle recursive."""
    return recursive(state)


def test_all_any_item_count_region_and_valid_alternatives():
    """Handle test all any item count region and valid alternatives."""
    rule = lambda s: (s.has('Key', 1) and s.count('Coin', 1) >= 3) or s.can_reach_region('Menu', 1)
    detail = trace(rule, {'Key': 1, 'Coin': 3})
    tree = detail['normalized_rule']
    assert tree['kind'] == 'ANY'
    assert {n['kind'] for n in walk(tree)} == {'ANY', 'ALL', 'ITEM', 'COUNT', 'REGION'}
    assert [n['satisfied'] for n in tree['children']] == [True, True]
    assert not any(x.get('kind') == 'region' for x in detail['consulted'])
    assert detail['alternative_branches'][0]['branches'][1]['satisfied'] is True


def test_helper_binding_default_and_source_line():
    """Handle test helper binding default and source line."""
    rule = lambda state: helper(state)
    detail = trace(rule)
    assert detail['normalized_rule']['kind'] == 'ITEM'
    assert detail['normalized_rule']['helper'] == 'helper'
    assert any(x['name'] == 'helper' and x['result'] is False for x in detail['helper_trace'])
    assert detail['explanation_complete']
    assert detail['normalized_rule']['source']['line'] > 0


def test_alternative_helpers_not_executed_by_analysis():
    """Handle test alternative helpers not executed by analysis."""
    calls = []
    def side_effect(s):
        """Handle side effect."""
        calls.append('ran')
        return True
    rule = lambda s: s.has('Key', 1) or side_effect(s)
    detail = trace(rule, {'Key': 1})
    assert calls == []
    assert detail['satisfied'] is True
    assert not detail['explanation_complete']
    assert 'control flow' in ' '.join(detail['explanation_unknown_reasons'])
    assert detail['logic_state'] == 'SATISFIED'


def test_helper_returns_are_not_overall_result():
    """Handle test helper returns are not overall result."""
    rule = lambda s: helper(s) or s.has('Other', 1)
    detail = trace(rule, {'Other': 1})
    assert detail['satisfied']
    assert next(x for x in detail['helper_trace'] if x['name'] == 'helper')['result'] is False


def test_group_and_event_forms():
    """Handle test group and event forms."""
    rule = lambda s: s.has_all(['Key', 'Victory'], 1) and s.has_group('Keys', 1, 2)
    detail = trace(rule, {'Key': 1, 'Victory': 1, 'Red': 1, 'Blue': 1}, {'Victory'})
    assert {'ALL', 'ITEM', 'EVENT', 'COUNT'} == {x['kind'] for x in walk(detail['normalized_rule'])}
    assert detail['normalized_rule']['satisfied'] is True


def test_negation_and_impossible_contradiction():
    """Handle test negation and impossible contradiction."""
    rule = lambda s: s.has('Key', 1) and not s.has('Key', 1)
    detail = trace(rule)
    assert detail['impossible_rule']
    assert detail['normalized_rule']['children'][1]['operator'] == '<'


def test_missing_item_not_impossible():
    """Handle test missing item not impossible."""
    rule = lambda s: s.has('Key', 1, 99)
    assert not trace(rule)['impossible_rule']


def test_count_bounds_and_constant_false():
    """Handle test count bounds and constant false."""
    rule = lambda s: s.count('Key', 1) < 0
    assert trace(rule)['impossible_rule']
    rule2 = lambda s: False
    assert trace(rule2)['impossible_rule']


def test_possible_or_branch_defeats_contradiction():
    """Handle test possible or branch defeats contradiction."""
    rule = lambda s: (s.has('Key', 1) and not s.has('Key', 1)) or s.has('Other', 1)
    assert not trace(rule)['impossible_rule']


def test_recursive_helper_error_and_restored_profiler():
    """Handle test recursive helper error and restored profiler."""
    before = sys.getprofile()
    detail = trace(recursive)
    assert sys.getprofile() is before
    assert detail['evaluation_error']['code'] == 'UNRESOLVABLE_HELPER'
    assert len(detail['helper_trace']) <= 128
    assert 'Recursive helper cycle' in ' '.join(detail['explanation_unknown_reasons'])
    assert detail['evaluation_error']['frames']


def test_missing_helper_is_not_ordinary_blocker():
    """Handle test missing helper is not ordinary blocker."""
    rule = lambda s: s.no_such_helper(1)
    detail = trace(rule)
    assert detail['logic_state'] == 'ERROR'
    assert detail['evaluation_error']['code'] == 'UNRESOLVABLE_HELPER'
    assert 'non-progression' in '\n'.join(explanation_lines(detail))


def test_non_boolean_error():
    """Handle test non boolean error."""
    rule = lambda s: 12
    assert trace(rule)['evaluation_error']['code'] == 'NON_BOOLEAN_RULE'


def test_generated_source_unavailable_keeps_executed_result():
    """Handle test generated source unavailable keeps executed result."""
    rule = eval(compile('lambda s: True', '<generated-test>', 'eval'))
    detail = trace(rule)
    assert detail['satisfied'] and not detail['error']
    assert not detail['explanation_complete']
    assert detail['explanation_unknown_reasons']


def test_ambiguous_same_line_lambdas_not_misidentified():
    """Handle test ambiguous same line lambdas not misidentified."""
    left, right = lambda s: s.has('Left', 1), lambda s: s.has('Right', 1)
    assert not trace(left)['explanation_complete']
    assert not trace(right)['explanation_complete']


def test_zip_apworld_source_and_cross_module_helper(tmp_path):
    """Handle test zip apworld source and cross module helper."""
    archive = tmp_path / 'fixture.apworld'
    with zipfile.ZipFile(archive, 'w') as z:
        z.writestr('fixturelogic/__init__.py', 'from .helpers import gate\ndef rule(s):\n    return gate(s)\n')
        z.writestr('fixturelogic/helpers.py', 'def gate(s):\n    return s.has("Key", 1)\n')
    sys.path.insert(0, str(archive))
    try:
        import fixturelogic
        detail = trace(fixturelogic.rule)
        assert detail['explanation_complete']
        assert '.apworld' in detail['normalized_rule']['source']['file']
        # Static provenance retains the helper source as well as call-site source.
        assert detail['normalized_rule']['helper'] == 'gate'
        assert 'helpers.py' in detail['normalized_rule']['source']['file']
    finally:
        sys.path.remove(str(archive))
        for key in list(sys.modules):
            if key.startswith('fixturelogic'): del sys.modules[key]


def test_unknown_parent_propagates_only_through_potentially_open_edges():
    """Handle test unknown parent propagates only through potentially open edges."""
    def edge(name, source, target, ok=False, error=''):
        """Handle edge."""
        return dict(name=name, source_region=source, target_region=target, satisfied=ok, error=error)
    edges = [edge('Broken', 'Menu', 'A', error='Missing helper'), edge('Open', 'A', 'B', True),
             edge('Blocked', 'A', 'C'), edge('Cycle', 'B', 'A', True)]
    result = uncertain_regions({'Menu'}, edges)
    assert set(result) == {'A', 'B'}
    assert 'Broken' in result['B']
    assert uncertain_regions({'Menu', 'A', 'B'}, edges) == {}


def test_explorer_preserves_alternatives_and_unknown():
    """Handle test explorer preserves alternatives and unknown."""
    rule = lambda s: s.has('Key', 1) or s.no_such_helper(1)
    detail = trace(rule)
    tree = display_tree(detail)
    assert tree['kind'] == 'or'
    assert tree['satisfied'] is None
    assert tree['children'][1]['kind'] == 'opaque'
    assert 'Logic evaluation failed' in tree['detail']


def test_incremental_dependencies_include_unvisited_branch():
    """Handle test incremental dependencies include unvisited branch."""
    from wayfinder.logic.incremental import IncrementalAPWorldEvaluator
    rule = lambda s: s.has('Key', 1) or s.has('Other', 1)
    detail = trace(rule, {'Key': 1})
    evaluator = object.__new__(IncrementalAPWorldEvaluator)
    deps, unsafe = evaluator._dependency_keys(detail)
    assert 'item:Other' in deps


def test_uncertain_progression_not_reported_exhausted():
    """Handle test uncertain progression not reported exhausted."""
    from wayfinder.logic.progression_intelligence import waiting_analysis
    snapshot = SimpleNamespace(locations=[SimpleNamespace(name='Check', status='unknown', ignored=False, unknown_reason='Logic evaluation failed')],
                               hints=[{'location': 'Other'}], inventory=[], goal_detail={})
    result = waiting_analysis(snapshot)
    assert result.state == 'unknown'
    assert 'exhausted' not in result.summary


def test_generated_arithmetic_count_and_partial():
    """Handle test generated arithmetic count and partial."""
    from functools import partial
    def requirement(s, quantity):
        """Handle requirement."""
        return s.has('Key', 1, quantity + 1)
    detail = trace(partial(requirement, quantity=2), {'Key': 2})
    assert detail['normalized_rule']['required'] == 3
    assert detail['normalized_rule']['satisfied'] is False


def test_direct_prog_items_normalization():
    """Handle test direct prog items normalization."""
    rule = lambda s: not s.prog_items[1]['Level'] < 5
    detail = trace(rule, {'Level': 6})
    assert detail['normalized_rule']['kind'] == 'COUNT'
    assert detail['normalized_rule']['operator'] == '>='
    assert detail['normalized_rule']['satisfied'] is True


def test_unique_count_and_count_mapping():
    """Handle test unique count and count mapping."""
    rule = lambda s: s.has_all_counts({'Key': 2}, 1) and s.has_from_list_unique(['Red', 'Blue'], 1, 2)
    detail = trace(rule, {'Key': 2, 'Red': 10})
    assert detail['normalized_rule']['satisfied'] is False
    count = detail['normalized_rule']['children'][1]
    assert count['unique'] and count['have'] == 1


def test_unswept_events_are_classified_from_producers():
    """Handle test unswept events are classified from producers."""
    from wayfinder.logic.rule_explanation import annotate_events
    rule = lambda s: s.has('Victory', 1)
    detail = trace(rule)
    annotate_events([detail], {'Victory'})
    assert detail['normalized_rule']['kind'] == 'EVENT'
    assert detail['normalized_rule']['satisfied'] is False


def test_error_redaction_and_serialization():
    """Handle test error redaction and serialization."""
    import json
    def broken(s):
        """Handle broken."""
        raise RuntimeError('password=private-example')
    detail = trace(broken)
    data = json.dumps(detail)
    assert 'private-example' not in data
    assert '[REDACTED]' in data


def test_explicit_remote_player_explanation_is_unknown():
    """Handle test explicit remote player explanation is unknown."""
    rule = lambda s: s.has('Key', 2)
    detail = trace(rule)
    assert 'Remote player' in ' '.join(detail['explanation_unknown_reasons'])


def test_map_does_not_treat_logic_failure_as_nonprogression():
    """Handle test map does not treat logic failure as nonprogression."""
    from wayfinder.app.app import WayFinderApp
    app = object.__new__(WayFinderApp)
    loc = SimpleNamespace(status='unknown', ignored=False, unknown_reason='Logic evaluation failed: missing helper')
    assert app._map_effective_location_status(loc) == 'unknown'
