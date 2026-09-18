"""World dependency installation paths and helpers."""

from .archipelago_core import AP_CORE_SOURCE, DEPENDENCIES_DIR, DEPENDENCY_REPORT
from wayfinder.runtime.dependency_manager import install_all_dependencies, dependency_report_ok, load_dependency_report, format_dependency_failure_report

__all__ = [
    "AP_CORE_SOURCE",
    "DEPENDENCIES_DIR",
    "DEPENDENCY_REPORT",
    "install_all_dependencies",
    "dependency_report_ok",
    "load_dependency_report",
    "format_dependency_failure_report",
]
