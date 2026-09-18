"""Provide rules support."""
# /**
#  * Module: wayfinder.logic/rules.py
#  * Purpose: Core tracker module for rules; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Protocol


# /**
#  * Class: RuleContext
#  * Purpose: Encapsulate the RuleContext responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class RuleContext(Protocol):
    # Variable(s): `inventory` (inventory); named state retained for the surrounding calculation or subsequent calls.
    """Provide rule context behavior."""
    inventory: Mapping[str, int]
    # Variable(s): `events` (events); named state retained for the surrounding calculation or subsequent calls.
    events: set[str]
    # Variable(s): `options` (options); named state retained for the surrounding calculation or subsequent calls.
    options: Mapping[str, Any]
    # Variable(s): `state_values` (state values); named state retained for the surrounding calculation or subsequent calls.
    state_values: Mapping[str, Any]


# /**
#  * Class: RuleResult
#  * Purpose: Encapsulate the RuleResult responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class RuleResult:
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    """Provide rule result behavior."""
    kind: str
    # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
    label: str
    # Variable(s): `satisfied` (satisfied); named state retained for the surrounding calculation or subsequent calls.
    satisfied: bool | None
    # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
    detail: str = ""
    # Variable(s): `children` (children); named state retained for the surrounding calculation or subsequent calls.
    children: tuple["RuleResult", ...] = field(default_factory=tuple)
    # Variable(s): `error` (error); named state retained for the surrounding calculation or subsequent calls.
    error: str = ""

    # /**
    #  * Function: missing_labels
    #  * Purpose: Perform the missing labels operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def missing_labels(self) -> list[str]:
        """Return unsatisfied leaf requirements, suitable for /missing and UI hints."""
        if self.satisfied is True:
            return []
        if not self.children:
            return [self.label] if self.satisfied is False else []
        # Variable(s): `out` (out); named state retained for the surrounding calculation or subsequent calls.
        out: list[str] = []
        # Loop variable(s): `child` (child); each iteration represents the next value from the iterable below.
        for child in self.children:
            out.extend(child.missing_labels())
        return out


# /**
#  * Class: Rule
#  * Purpose: Encapsulate the Rule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
class Rule:
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    """Provide rule behavior."""
    kind = "rule"

    # /**
    #  * Function: evaluate
    #  * Purpose: Perform the evaluate operation while keeping the surrounding subsystem state consistent.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def evaluate(self, ctx: RuleContext) -> RuleResult:
        """Handle evaluate."""
        try:
            return self._evaluate(ctx)
        except Exception as exc:  # a broken rule must never collapse the whole tracker
            return RuleResult(self.kind, self.describe(), None, error=f"{type(exc).__name__}: {exc}")

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        """Handle evaluate."""
        raise NotImplementedError

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return self.kind

    # /**
    #  * Function: __and__
    #  * Purpose: Perform the and operation while keeping the surrounding subsystem state consistent.
    #  * @param other: Other supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __and__(self, other: "Rule") -> "Rule":
        """Handle and."""
        return AllRule((self, other))

    # /**
    #  * Function: __or__
    #  * Purpose: Perform the or operation while keeping the surrounding subsystem state consistent.
    #  * @param other: Other supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __or__(self, other: "Rule") -> "Rule":
        """Handle or."""
        return AnyRule((self, other))

    # /**
    #  * Function: __invert__
    #  * Purpose: Perform the invert operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def __invert__(self) -> "Rule":
        """Handle invert."""
        return NotRule(self)


# /**
#  * Class: ConstantRule
#  * Purpose: Encapsulate the ConstantRule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class ConstantRule(Rule):
    # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
    """Provide constant rule behavior."""
    value: bool
    # Variable(s): `label` (label); named state retained for the surrounding calculation or subsequent calls.
    label: str = "Always"
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind = "constant"

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        """Handle evaluate."""
        return RuleResult(self.kind, self.label, self.value)

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return self.label


# /**
#  * Class: ItemRule
#  * Purpose: Encapsulate the ItemRule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class ItemRule(Rule):
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide item rule behavior."""
    name: str
    # Variable(s): `count` (count); named state retained for the surrounding calculation or subsequent calls.
    count: int = 1
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind = "item"

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        # Variable(s): `have` (have); named state retained for the surrounding calculation or subsequent calls.
        """Handle evaluate."""
        have = int(ctx.inventory.get(self.name, 0))
        return RuleResult(self.kind, self.describe(), have >= self.count, f"{have}/{self.count}")

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return self.name if self.count == 1 else f"{self.name} x{self.count}"


# /**
#  * Class: EventRule
#  * Purpose: Encapsulate the EventRule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class EventRule(Rule):
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    """Provide event rule behavior."""
    name: str
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind = "event"

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        """Handle evaluate."""
        return RuleResult(self.kind, self.name, self.name in ctx.events)

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return self.name


# /**
#  * Class: ValueRule
#  * Purpose: Encapsulate the ValueRule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class ValueRule(Rule):
    # Variable(s): `source` (source); named state retained for the surrounding calculation or subsequent calls.
    """Provide value rule behavior."""
    source: str
    # Variable(s): `key` (key); named state retained for the surrounding calculation or subsequent calls.
    key: str
    # Variable(s): `expected` (expected); named state retained for the surrounding calculation or subsequent calls.
    expected: Any
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind = "value"

    # /**
    #  * Function: _mapping
    #  * Purpose: Perform the mapping operation while keeping the surrounding subsystem state consistent.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _mapping(self, ctx: RuleContext) -> Mapping[str, Any]:
        """Handle mapping."""
        if self.source == "option":
            return ctx.options
        if self.source == "state":
            return ctx.state_values
        raise ValueError(f"unknown value source {self.source!r}")

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        # Variable(s): `mapping` (mapping); named state retained for the surrounding calculation or subsequent calls.
        """Handle evaluate."""
        mapping = self._mapping(ctx)
        if self.key not in mapping:
            return RuleResult(self.source, self.describe(), None, "value unavailable")
        # Variable(s): `actual` (actual); named state retained for the surrounding calculation or subsequent calls.
        actual = mapping[self.key]
        return RuleResult(self.source, self.describe(), actual == self.expected, f"actual={actual!r}")

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return f"{self.source} {self.key} = {self.expected!r}"


# /**
#  * Class: AllRule
#  * Purpose: Encapsulate the AllRule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class AllRule(Rule):
    # Variable(s): `rules` (rules); named state retained for the surrounding calculation or subsequent calls.
    """Provide all rule behavior."""
    rules: tuple[Rule, ...]
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind = "all"

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        # Variable(s): `children` (children); named state retained for the surrounding calculation or subsequent calls.
        """Handle evaluate."""
        children = tuple(rule.evaluate(ctx) for rule in self.rules)
        if any(c.satisfied is False for c in children):
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value: bool | None = False
        elif any(c.satisfied is None for c in children):
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value = None
        else:
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value = True
        return RuleResult(self.kind, "All of", value, children=children)

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return " AND ".join(r.describe() for r in self.rules) or "Always"


# /**
#  * Class: AnyRule
#  * Purpose: Encapsulate the AnyRule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class AnyRule(Rule):
    # Variable(s): `rules` (rules); named state retained for the surrounding calculation or subsequent calls.
    """Provide any rule behavior."""
    rules: tuple[Rule, ...]
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind = "any"

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        # Variable(s): `children` (children); named state retained for the surrounding calculation or subsequent calls.
        """Handle evaluate."""
        children = tuple(rule.evaluate(ctx) for rule in self.rules)
        if any(c.satisfied is True for c in children):
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value: bool | None = True
        elif any(c.satisfied is None for c in children):
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value = None
        else:
            # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
            value = False
        return RuleResult(self.kind, "Any of", value, children=children)

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return " OR ".join(r.describe() for r in self.rules) or "Never"


# /**
#  * Class: NotRule
#  * Purpose: Encapsulate the NotRule responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class NotRule(Rule):
    # Variable(s): `rule` (rule); named state retained for the surrounding calculation or subsequent calls.
    """Provide not rule behavior."""
    rule: Rule
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    kind = "not"

    # /**
    #  * Function: _evaluate
    #  * Purpose: Evaluate evaluate against the current tracker state.
    #  * @param ctx: Context supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def _evaluate(self, ctx: RuleContext) -> RuleResult:
        # Variable(s): `child` (child); named state retained for the surrounding calculation or subsequent calls.
        """Handle evaluate."""
        child = self.rule.evaluate(ctx)
        # Variable(s): `value` (value); named state retained for the surrounding calculation or subsequent calls.
        value = None if child.satisfied is None else not child.satisfied
        return RuleResult(self.kind, f"Not {self.rule.describe()}", value, children=(child,))

    # /**
    #  * Function: describe
    #  * Purpose: Perform the describe operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def describe(self) -> str:
        """Handle describe."""
        return f"NOT ({self.rule.describe()})"


# /**
#  * Function: always
#  * Purpose: Perform the always operation while keeping the surrounding subsystem state consistent.
#  * @param label: Label supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def always(label: str = "Always") -> Rule:
    """Handle always."""
    return ConstantRule(True, label)


# /**
#  * Function: never
#  * Purpose: Perform the never operation while keeping the surrounding subsystem state consistent.
#  * @param label: Label supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def never(label: str = "Never") -> Rule:
    """Handle never."""
    return ConstantRule(False, label)


# /**
#  * Function: item
#  * Purpose: Perform the item operation while keeping the surrounding subsystem state consistent.
#  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
#  * @param count: Count supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def item(name: str, count: int = 1) -> Rule:
    """Handle item."""
    return ItemRule(name, max(1, int(count)))


# /**
#  * Function: event
#  * Purpose: Perform the event operation while keeping the surrounding subsystem state consistent.
#  * @param name: Name supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def event(name: str) -> Rule:
    """Handle event."""
    return EventRule(name)


# /**
#  * Function: option
#  * Purpose: Perform the option operation while keeping the surrounding subsystem state consistent.
#  * @param key: Key supplied by the caller; see type hints and call sites for domain constraints.
#  * @param expected: Expected supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def option(key: str, expected: Any) -> Rule:
    """Handle option."""
    return ValueRule("option", key, expected)


# /**
#  * Function: state_value
#  * Purpose: Perform the state value operation while keeping the surrounding subsystem state consistent.
#  * @param key: Key supplied by the caller; see type hints and call sites for domain constraints.
#  * @param expected: Expected supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def state_value(key: str, expected: Any) -> Rule:
    """Handle state value."""
    return ValueRule("state", key, expected)


# /**
#  * Function: all_of
#  * Purpose: Perform the all of operation while keeping the surrounding subsystem state consistent.
#  * @param rules: Rules supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def all_of(*rules: Rule | Iterable[Rule]) -> Rule:
    """Handle all of."""
    if len(rules) == 1 and not isinstance(rules[0], Rule):
        # Variable(s): `seq` (seq); named state retained for the surrounding calculation or subsequent calls.
        seq = tuple(rules[0])  # type: ignore[arg-type]
    else:
        # Variable(s): `seq` (seq); named state retained for the surrounding calculation or subsequent calls.
        seq = tuple(rules)  # type: ignore[arg-type]
    if not seq:
        return always()
    if len(seq) == 1:
        return seq[0]
    return AllRule(seq)


# /**
#  * Function: any_of
#  * Purpose: Perform the any of operation while keeping the surrounding subsystem state consistent.
#  * @param rules: Rules supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def any_of(*rules: Rule | Iterable[Rule]) -> Rule:
    """Handle any of."""
    if len(rules) == 1 and not isinstance(rules[0], Rule):
        # Variable(s): `seq` (seq); named state retained for the surrounding calculation or subsequent calls.
        seq = tuple(rules[0])  # type: ignore[arg-type]
    else:
        # Variable(s): `seq` (seq); named state retained for the surrounding calculation or subsequent calls.
        seq = tuple(rules)  # type: ignore[arg-type]
    if not seq:
        return never()
    if len(seq) == 1:
        return seq[0]
    return AnyRule(seq)


# /**
#  * Function: not_
#  * Purpose: Perform the not operation while keeping the surrounding subsystem state consistent.
#  * @param rule: Rule supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def not_(rule: Rule) -> Rule:
    """Handle not."""
    return NotRule(rule)
