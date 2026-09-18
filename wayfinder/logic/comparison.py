"""Provide comparison support."""
# /**
#  * Module: wayfinder.logic/comparison.py
#  * Purpose: Core tracker module for comparison; contains format-neutral or APWorld logic used to calculate WayFinder state.
#  * Maintenance: Prefer descriptive names, explicit state transitions, and conservative fallbacks over clever compact code.
#  */

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from .logic_api import LogicSnapshot


# /**
#  * Class: LogicDifference
#  * Purpose: Encapsulate the LogicDifference responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass(frozen=True)
class LogicDifference:
    # Variable(s): `kind` (kind); named state retained for the surrounding calculation or subsequent calls.
    """Provide logic difference behavior."""
    kind: str
    # Variable(s): `name` (name); named state retained for the surrounding calculation or subsequent calls.
    name: str
    # Variable(s): `reference` (reference); named state retained for the surrounding calculation or subsequent calls.
    reference: str
    # Variable(s): `candidate` (candidate); named state retained for the surrounding calculation or subsequent calls.
    candidate: str
    # Variable(s): `detail` (detail); named state retained for the surrounding calculation or subsequent calls.
    detail: str = ""


# /**
#  * Class: LogicComparisonReport
#  * Purpose: Encapsulate the LogicComparisonReport responsibilities and state used by this module.
#  * @state: Instance attributes hold the durable state needed by this responsibility.
#  */
@dataclass
class LogicComparisonReport:
    # Variable(s): `reference_name` (reference name); named state retained for the surrounding calculation or subsequent calls.
    """Provide logic comparison report behavior."""
    reference_name: str
    # Variable(s): `candidate_name` (candidate name); named state retained for the surrounding calculation or subsequent calls.
    candidate_name: str
    # Variable(s): `differences` (differences); named state retained for the surrounding calculation or subsequent calls.
    differences: list[LogicDifference] = field(default_factory=list)
    # Variable(s): `reference_counts` (reference counts); named state retained for the surrounding calculation or subsequent calls.
    reference_counts: dict[str, int] = field(default_factory=dict)
    # Variable(s): `candidate_counts` (candidate counts); named state retained for the surrounding calculation or subsequent calls.
    candidate_counts: dict[str, int] = field(default_factory=dict)

    # /**
    #  * Function: passed
    #  * Purpose: Perform the passed operation while keeping the surrounding subsystem state consistent.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    @property
    def passed(self) -> bool:
        """Handle passed."""
        return not self.differences

    # /**
    #  * Function: format_text
    #  * Purpose: Format text into human-readable output.
    #  * @param state_label: State label supplied by the caller; see type hints and call sites for domain constraints.
    #  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
    #  */
    def format_text(self, state_label: str = "") -> str:
        # Variable(s): `lines` (lines); named state retained for the surrounding calculation or subsequent calls.
        """Return format text."""
        lines = ["WayFinder Logic Comparison"]
        if state_label:
            lines.append(f"State: {state_label}")
        lines.extend(["", self.reference_name])
        # Loop variable(s): `key` (key), `value` (value); each iteration represents the next value from the iterable below.
        for key, value in self.reference_counts.items():
            lines.append(f"  {key}: {value}")
        lines.extend(["", self.candidate_name])
        # Loop variable(s): `key` (key), `value` (value); each iteration represents the next value from the iterable below.
        for key, value in self.candidate_counts.items():
            lines.append(f"  {key}: {value}")
        lines.extend(["", f"Differences: {len(self.differences)}", "PASS" if self.passed else "FAIL"])
        # Loop variable(s): `difference` (difference); each iteration represents the next value from the iterable below.
        for difference in self.differences:
            lines.extend(["", "DIFFERENCE", f"  Type: {difference.kind}", f"  Target: {difference.name}", f"  Reference: {difference.reference}", f"  Candidate: {difference.candidate}"])
            if difference.detail:
                lines.append(f"  Detail: {difference.detail}")
        return "\n".join(lines)


# /**
#  * Function: _sets
#  * Purpose: Update sets state in a controlled way.
#  * @param snapshot: Snapshot supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def _sets(snapshot: Any) -> dict[str, set[str]]:
    """Handle sets."""
    if isinstance(snapshot, LogicSnapshot):
        return {
            "Locations reachable": {n for n, x in snapshot.locations.items() if x.reachable},
            "Regions reachable": set(snapshot.reachable_regions),
            "Entrances reachable": {n for n, x in snapshot.entrances.items() if x.reachable},
            "Events swept": set(snapshot.events),
        }
    # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
    locations = getattr(snapshot, "reachable_locations", set())
    if not isinstance(locations, set):
        # Variable(s): `locations` (locations); named state retained for the surrounding calculation or subsequent calls.
        locations = set(locations or ())
    return {
        "Locations reachable": set(locations),
        "Regions reachable": set(getattr(snapshot, "reachable_regions", set()) or ()),
        "Entrances reachable": set(getattr(snapshot, "reachable_entrances", set()) or ()),
        "Events swept": set(getattr(snapshot, "events", set()) or ()),
    }


# /**
#  * Function: compare_snapshots
#  * Purpose: Compare snapshots values and report meaningful differences.
#  * @param reference: Reference supplied by the caller; see type hints and call sites for domain constraints.
#  * @param candidate: Candidate supplied by the caller; see type hints and call sites for domain constraints.
#  * @param reference_name: Reference name supplied by the caller; see type hints and call sites for domain constraints.
#  * @param candidate_name: Candidate name supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def compare_snapshots(reference: Any, candidate: Any, *, reference_name: str = "Reference Engine", candidate_name: str = "Candidate Engine") -> LogicComparisonReport:
    # Variable(s): `reference_sets` (reference sets); named state retained for the surrounding calculation or subsequent calls.
    """Handle compare snapshots."""
    reference_sets = _sets(reference)
    # Variable(s): `candidate_sets` (candidate sets); named state retained for the surrounding calculation or subsequent calls.
    candidate_sets = _sets(candidate)
    # Variable(s): `report` (report); named state retained for the surrounding calculation or subsequent calls.
    report = LogicComparisonReport(reference_name, candidate_name)
    report.reference_counts = {k: len(v) for k, v in reference_sets.items()}
    report.candidate_counts = {k: len(v) for k, v in candidate_sets.items()}
    # Loop variable(s): `kind` (kind); each iteration represents the next value from the iterable below.
    for kind in reference_sets:
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for name in sorted(reference_sets[kind] - candidate_sets[kind]):
            report.differences.append(LogicDifference(kind, name, "reachable", "not reachable"))
        # Loop variable(s): `name` (name); each iteration represents the next value from the iterable below.
        for name in sorted(candidate_sets[kind] - reference_sets[kind]):
            report.differences.append(LogicDifference(kind, name, "not reachable", "reachable"))
    return report


# /**
#  * Function: compare_engines
#  * Purpose: Compare engines values and report meaningful differences.
#  * @param reference: Reference supplied by the caller; see type hints and call sites for domain constraints.
#  * @param candidate: Candidate supplied by the caller; see type hints and call sites for domain constraints.
#  * @param kwargs: Kwargs supplied by the caller; see type hints and call sites for domain constraints.
#  * @returns: See the return annotation and implementation; side effects are documented inline where they occur.
#  */
def compare_engines(reference: Callable[[], Any], candidate: Callable[[], Any], **kwargs: Any) -> LogicComparisonReport:
    """Handle compare engines."""
    return compare_snapshots(reference(), candidate(), **kwargs)
