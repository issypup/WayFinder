import sys
from collections import Counter
from types import ModuleType

from wayfinder.logic.apworld_adapter import NativeAPState


def test_apworld_installed_collectionstate_helper_is_delegated(monkeypatch):
    module=ModuleType("BaseClasses")
    class CollectionState:
        def _game_helper(self, player):
            return self.has("Hookshot", player)
    module.CollectionState=CollectionState
    monkeypatch.setitem(sys.modules, "BaseClasses", module)
    state=NativeAPState(1, Counter({"Hookshot": 1}), set(), set())
    assert state._game_helper(1) is True
