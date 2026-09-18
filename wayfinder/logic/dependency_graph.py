"""Provide dependency graph support."""
# /**
#  * Module: wayfinder.logic/dependency_graph.py
#  * Purpose: Core tracker module for dependency graph; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


# /**
#  * Class: DependencyGraph
#  * Purpose: Encapsulate the DependencyGraph responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class DependencyGraph:
    """Conservative dependency index derived from rule traces.

    Nodes are prefixed (location:, entrance:, event:, goal:). Dependency keys are
    item:, region:, event:, option:, state:, unsupported:, or opaque:. Unknown or
    opaque rules are marked unsafe so callers can fall back to a full evaluation.
    """

    # Variable(s): `dependency_to_nodes` (dependency to nodes); named state retained for the surrounding calculation or subsequent calls.
    dependency_to_nodes: dict[str, set[str]] = field(default_factory=dict)
    # Variable(s): `node_to_dependencies` (node to dependencies); named state retained for the surrounding calculation or subsequent calls.
    node_to_dependencies: dict[str, set[str]] = field(default_factory=dict)
    # Variable(s): `unsafe_nodes` (unsafe nodes); named state retained for the surrounding calculation or subsequent calls.
    unsafe_nodes: set[str] = field(default_factory=set)

    # /**
    #  * Function: add
    #  * Purpose: Perform the add operation while keeping the surrounding subsystem state consistent.
    #  * @param node: Node supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param dependencies: Dependencies supplied by the caller; see type hints and call sites for domain constraints.
    #  * @param unsafe: Unsafe supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def add(self, node: str, dependencies: Iterable[str], *, unsafe: bool = False) -> None:
        # Variable(s): `dependencies_set` (dependencies set); named state retained for the surrounding calculation or subsequent calls.
        """Handle add."""
        dependencies_set = {str(dependency) for dependency in dependencies if str(dependency)}
        # A rule can expose a different dependency set after an option/event path
        # changes. Remove the old reverse-index entries before replacing it so
        # stale dependencies do not cause unrelated rules to be reevaluated.
        previous=self.node_to_dependencies.get(node,set())
        for dependency_key in previous - dependencies_set:
            nodes=self.dependency_to_nodes.get(dependency_key)
            if nodes is not None:
                nodes.discard(node)
                if not nodes:
                    self.dependency_to_nodes.pop(dependency_key,None)
        self.node_to_dependencies[node] = dependencies_set
        # Loop variable(s): `dependency_key` (dependency key); each iteration represents the next value from the iterable below.
        for dependency_key in dependencies_set:
            self.dependency_to_nodes.setdefault(dependency_key, set()).add(node)
        if unsafe:
            self.unsafe_nodes.add(node)
        else:
            self.unsafe_nodes.discard(node)

    # /**
    #  * Function: affected
    #  * Purpose: Perform the affected operation while keeping the surrounding subsystem state consistent.
    #  * @param changed_dependencies: Changed dependencies supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def affected(self, changed_dependencies: Iterable[str]) -> set[str]:
        # Variable(s): `affected_nodes` (affected nodes); named state retained for the surrounding calculation or subsequent calls.
        """Handle affected."""
        affected_nodes: set[str] = set()
        # Loop variable(s): `dependency_key` (dependency key); each iteration represents the next value from the iterable below.
        for dependency_key in changed_dependencies:
            affected_nodes.update(self.dependency_to_nodes.get(str(dependency_key), ()))
        return affected_nodes

    # /**
    #  * Function: is_safe_for
    #  * Purpose: Determine whether safe for is true for the supplied state.
    #  * @param nodes: Nodes supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def is_safe_for(self, nodes: Iterable[str]) -> bool:
        """Return is safe for."""
        return not bool(set(nodes) & self.unsafe_nodes)
