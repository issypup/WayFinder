"""WayFinder pytest reporter that summarizes results per test .py file."""

# sig:kuro:pluralchat

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

_TERMINAL = None
_RESULTS = defaultdict(lambda: {"passed": 0, "failed": 0, "skipped": 0})


def pytest_configure(config):
    """Capture pytest's terminal reporter."""
    global _TERMINAL
    _TERMINAL = config.pluginmanager.getplugin("terminalreporter")


def pytest_report_teststatus(report, config):
    """Suppress normal pytest dots/node IDs."""
    if report.when == "call":
        return report.outcome, "", ""
    return None


def pytest_runtest_logreport(report):
    """Count completed test functions by their containing Python test file."""
    if report.when != "call":
        return

    file_name = Path(report.nodeid.split("::", 1)[0]).name

    if report.passed:
        _RESULTS[file_name]["passed"] += 1
    elif report.skipped:
        _RESULTS[file_name]["skipped"] += 1
    else:
        _RESULTS[file_name]["failed"] += 1


def pytest_terminal_summary(terminalreporter, exitstatus, config):
    """Print one clear result line for every test .py file."""
    terminalreporter.write_sep("=", "WayFinder Test File Results")

    total_files = 0
    passed_files = 0
    failed_files = 0

    for file_name in sorted(_RESULTS):
        counts = _RESULTS[file_name]
        total = counts["passed"] + counts["failed"] + counts["skipped"]
        total_files += 1

        if counts["failed"]:
            result = "FAILED"
            failed_files += 1
        elif counts["skipped"] == total:
            result = "SKIPPED"
        else:
            result = "PASSED"
            passed_files += 1

        terminalreporter.write_line(
            f"{file_name:<44} {result:<7} "
            f"({counts['passed']}/{total} tests passed"
            + (f", {counts['failed']} failed" if counts["failed"] else "")
            + (f", {counts['skipped']} skipped" if counts["skipped"] else "")
            + ")"
        )

    terminalreporter.write_sep("=", "WayFinder Test File Summary")
    terminalreporter.write_line(f"Test files completed: {total_files}")
    terminalreporter.write_line(f"Files passed:         {passed_files}")
    terminalreporter.write_line(f"Files failed:         {failed_files}")

    passed = len(terminalreporter.stats.get("passed", []))
    failed = len(terminalreporter.stats.get("failed", []))
    skipped = len(terminalreporter.stats.get("skipped", []))
    total = passed + failed + skipped
    terminalreporter.write_line("")
    terminalreporter.write_line(f"Individual tests:     {passed}/{total} passed")
    terminalreporter.write_line(f"Failed tests:         {failed}")
    terminalreporter.write_line(f"Skipped tests:        {skipped}")
