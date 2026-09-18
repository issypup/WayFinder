#!/usr/bin/env python3
"""Generate PROJECT_STRUCTURE.md from WayFinder's real Python import graph.

The analyser resolves Python absolute and relative imports using AST semantics. It
never prefixes standard-library/third-party imports with the current package, and
reverse importer lists are built from the same resolved graph.
"""

# sig:kuro:pluralchat

from __future__ import annotations

import argparse
import ast
import importlib.util
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[1]
PACKAGE_ROOT = ROOT / "wayfinder"
OUTPUT = ROOT / "PROJECT_STRUCTURE.md"

SECTION_ORDER = (
    ("wayfinder/app/", "Application composition and GUI packages"),
    ("wayfinder/connection/", "Connection subsystem"),
    ("wayfinder/logic/", "Logic subsystem"),
    ("wayfinder/maps/", "Map data subsystem"),
    ("wayfinder/runtime/", "Runtime subsystem"),
    ("wayfinder/setup/", "Setup subsystem"),
)

PACKAGE_PURPOSES = {
    "wayfinder/app/core/": "Shared GUI contracts and developer support.",
    "wayfinder/app/controllers/": "GUI orchestration and lifecycle controllers.",
    "wayfinder/app/pages/": "Top-level navigation pages.",
    "wayfinder/app/ui/": "Reusable Tk shell, styles, panels, and dialogs.",
    "wayfinder/app/map/": "Map presentation, rendering, marker, navigation, and interaction subsystem.",
}

FORBIDDEN_IMPORTS = (
    # Domain/runtime layers must never depend upward on GUI implementation.
    ("wayfinder.connection", "wayfinder.app"),
    ("wayfinder.logic", "wayfinder.app"),
    ("wayfinder.maps", "wayfinder.app"),
    ("wayfinder.runtime", "wayfinder.app"),
    ("wayfinder.setup", "wayfinder.app"),
    ("wayfinder.storage", "wayfinder.app"),
    # The reusable map subsystem is below the top-level Map page.
    ("wayfinder.app.map", "wayfinder.app.pages"),
)

@dataclass(frozen=True)
class ModuleInfo:
    """Provide module info behavior."""
    name: str
    path: Path
    relative_path: Path
    source: str
    tree: ast.Module

    @property
    def package(self) -> str:
        """Handle package."""
        if self.path.name == "__init__.py":
            return self.name
        return self.name.rpartition(".")[0]


def module_name(path: Path) -> str:
    """Handle module name."""
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def production_modules() -> dict[str, ModuleInfo]:
    """Handle production modules."""
    result: dict[str, ModuleInfo] = {}
    for path in sorted(PACKAGE_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        name = module_name(path)
        result[name] = ModuleInfo(name, path, path.relative_to(ROOT), source, ast.parse(source, filename=str(path)))
    return result


def longest_internal_prefix(name: str, module_names: set[str]) -> str | None:
    """Handle longest internal prefix."""
    candidate = name
    while candidate:
        if candidate in module_names:
            return candidate
        candidate = candidate.rpartition(".")[0]
    return None


def resolve_from(info: ModuleInfo, node: ast.ImportFrom) -> str:
    """Return resolve from."""
    if node.level:
        suffix = node.module or ""
        relative = "." * node.level + suffix
        return importlib.util.resolve_name(relative, info.package)
    return node.module or ""


class ImportCollector(ast.NodeVisitor):
    """Collect imports while distinguishing module-scope from lazy/local imports."""

    def __init__(self) -> None:
        """Handle init."""
        self.scope_depth = 0
        self.top_level: list[ast.Import | ast.ImportFrom] = []
        self.local: list[ast.Import | ast.ImportFrom] = []

    def visit_Import(self, node: ast.Import) -> None:
        """Handle visit  import."""
        (self.local if self.scope_depth else self.top_level).append(node)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """Handle visit  import from."""
        (self.local if self.scope_depth else self.top_level).append(node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        """Handle visit  function def."""
        self.scope_depth += 1
        for stmt in node.body:
            self.visit(stmt)
        self.scope_depth -= 1

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # Imports executed in a class body happen at module import time. Methods do not.
        """Handle visit  class def."""
        for stmt in node.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self.visit(stmt)
            else:
                self.visit(stmt)


def _resolve_import_nodes(info: ModuleInfo, nodes: Iterable[ast.Import | ast.ImportFrom], module_names: set[str]) -> tuple[set[str], set[str]]:
    """Handle resolve import nodes."""
    internal: set[str] = set()
    external: set[str] = set()
    stdlib = getattr(sys, "stdlib_module_names", set())

    for node in nodes:
        raw_names: list[str] = []
        if isinstance(node, ast.Import):
            raw_names.extend(alias.name for alias in node.names)
        else:
            try:
                base = resolve_from(info, node)
            except (ImportError, ValueError):
                base = node.module or ""
            if base:
                child_modules: list[str] = []
                needs_base = False
                for alias in node.names:
                    if alias.name == "*":
                        needs_base = True
                        continue
                    child = f"{base}.{alias.name}"
                    if child in module_names:
                        child_modules.append(child)
                    else:
                        needs_base = True
                if needs_base or not child_modules:
                    raw_names.append(base)
                raw_names.extend(child_modules)

        for raw in raw_names:
            if not raw or raw == info.name:
                continue
            internal_name = longest_internal_prefix(raw, module_names)
            if internal_name:
                if internal_name != info.name:
                    internal.add(internal_name)
                continue
            top = raw.split(".", 1)[0]
            if top == "__future__":
                continue
            external.add(top if top in stdlib else raw)

    return internal, external


def imports_for(info: ModuleInfo, module_names: set[str]) -> tuple[set[str], set[str], set[str], set[str]]:
    """Handle imports for."""
    collector = ImportCollector()
    collector.visit(info.tree)
    static_internal, static_external = _resolve_import_nodes(info, collector.top_level, module_names)
    lazy_internal, lazy_external = _resolve_import_nodes(info, collector.local, module_names)
    lazy_internal -= static_internal
    lazy_external -= static_external
    return static_internal, static_external, lazy_internal, lazy_external

def exports_for(info: ModuleInfo) -> list[str]:
    """Handle exports for."""
    explicit_all: list[str] | None = None
    exports: set[str] = set()
    for node in info.tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and not node.name.startswith("_"):
            exports.add(node.name)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets: list[ast.expr] = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    name = target.id
                    value = node.value
                    if name == "__all__" and isinstance(value, (ast.List, ast.Tuple)):
                        vals = []
                        for item in value.elts:
                            if isinstance(item, ast.Constant) and isinstance(item.value, str):
                                vals.append(item.value)
                        explicit_all = vals
                    elif name.isupper() and not name.startswith("_"):
                        exports.add(name)
    return sorted(explicit_all if explicit_all is not None else exports)


def purpose_for(info: ModuleInfo) -> str:
    """Handle purpose for."""
    doc = ast.get_docstring(info.tree, clean=True)
    if doc:
        return doc.splitlines()[0].strip()
    for line in info.source.splitlines()[:15]:
        if "Purpose:" in line:
            return line.split("Purpose:", 1)[1].strip(" */#\t")
    if info.path.name == "__init__.py":
        return "Package boundary/facade."
    return f"Implementation module for {info.path.stem.replace('_', ' ')}."


def fmt_names(names: Iterable[str], empty: str) -> str:
    """Handle fmt names."""
    values = sorted(set(names))
    return ", ".join(f"`{value}`" for value in values) if values else empty


def version() -> str:
    """Handle version."""
    init = (PACKAGE_ROOT / "__init__.py").read_text(encoding="utf-8")
    tree = ast.parse(init)
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "__version__" and isinstance(node.value, ast.Constant):
                    return str(node.value.value)
    return "unknown"


def tree_lines() -> list[str]:
    """Handle tree lines."""
    lines = ["```text"]

    def render_dir(path: Path, prefix: str = "") -> None:
        """Handle render dir."""
        entries = [p for p in sorted(path.iterdir(), key=lambda x: (x.is_file(), x.name.lower())) if "__pycache__" not in p.parts]
        entries = [p for p in entries if not (p.is_file() and p.suffix in {".pyc", ".pyo"})]
        for index, entry in enumerate(entries):
            last = index == len(entries) - 1
            branch = "└── " if last else "├── "
            lines.append(prefix + branch + entry.name + ("/" if entry.is_dir() else ""))
            if entry.is_dir():
                render_dir(entry, prefix + ("    " if last else "│   "))

    for root_name in ("wayfinder", "pytest", "tools"):
        base = ROOT / root_name
        if base.exists():
            lines.append(f"{root_name}/")
            render_dir(base, "")
    for name in ("run_wayfinder.py", "run_pytests.py", "requirements.txt", "BUILD-SINGLE-EXE.bat", "PROJECT_STRUCTURE.md"):
        if (ROOT / name).exists():
            lines.append(name)
    lines.append("```")
    return lines

def dependency_direction(name: str, graph: dict[str, set[str]], lazy_graph: dict[str, set[str]]) -> str:
    """Handle dependency direction."""
    deps = graph.get(name, set())
    reciprocal = sorted(dep for dep in deps if name in graph.get(dep, set()) and dep != name)
    if reciprocal:
        return "Reciprocal **import-time** dependency with " + ", ".join(f"`{x}`" for x in reciprocal) + ". Review for initialization-cycle risk."
    lazy_backrefs = sorted(
        dep for dep in lazy_graph.get(name, set())
        if name in graph.get(dep, set()) or name in lazy_graph.get(dep, set())
    )
    if lazy_backrefs:
        return "One-way at import time; lazy/runtime back-reference(s) to " + ", ".join(f"`{x}`" for x in lazy_backrefs) + ". This is runtime coupling, not an import-time cycle."
    return "One-way at import-time level. GUI mixins may additionally share callback/state contracts through `WayFinderApp`." if name.startswith("wayfinder.app.") else "One-way at import-time level."

def forbidden_edges(graph: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Handle forbidden edges."""
    found = []
    for source, deps in graph.items():
        for dep in deps:
            for source_prefix, forbidden_prefix in FORBIDDEN_IMPORTS:
                if (source == source_prefix or source.startswith(source_prefix + ".")) and (dep == forbidden_prefix or dep.startswith(forbidden_prefix + ".")):
                    found.append((source, dep))
    return sorted(set(found))


def direct_cycles(graph: dict[str, set[str]]) -> list[tuple[str, str]]:
    """Handle direct cycles."""
    cycles = set()
    for source, deps in graph.items():
        for dep in deps:
            if source in graph.get(dep, set()):
                cycles.add(tuple(sorted((source, dep))))
    return sorted(cycles)


def generate() -> str:
    """Handle generate."""
    modules = production_modules()
    module_names = set(modules)
    graph: dict[str, set[str]] = {}
    externals: dict[str, set[str]] = {}
    lazy_graph: dict[str, set[str]] = {}
    lazy_externals: dict[str, set[str]] = {}
    for name, info in modules.items():
        graph[name], externals[name], lazy_graph[name], lazy_externals[name] = imports_for(info, module_names)

    reverse: dict[str, set[str]] = defaultdict(set)
    lazy_reverse: dict[str, set[str]] = defaultdict(set)
    for source, deps in graph.items():
        for dep in deps:
            reverse[dep].add(source)
    for source, deps in lazy_graph.items():
        for dep in deps:
            lazy_reverse[dep].add(source)

    lines = [
        "# WayFinder Project Structure & Dependency Guide",
        "",
        f"> Generated from the source tree for **WayFinder {version()}** by `tools/generate_project_structure.py`.",
        "",
        "# Purpose of this document",
        "",
        "This is the maintainers’ map of the repository. The dependency information below is generated from Python AST imports, so absolute imports remain absolute, relative imports are resolved against their real package, and reverse importer lists come from the same dependency graph.",
        "",
        "# High-level dependency direction",
        "",
        "```text",
        "run_wayfinder.py",
        "      │",
        "      ▼",
        "wayfinder.app.app  (composition root)",
        "  ├──► app.pages / app.ui / app.controllers / app.map",
        "  ├──► connection / logic / maps / setup / storage",
        "  └──► runtime transport/process orchestration",
        "",
        "Lower-level packages (`connection`, `logic`, `maps`, `runtime`, `setup`, `storage`) must not import `wayfinder.app.*`.",
        "`app.map` is below `app.pages.map_page`; it must not import `app.pages.*`.",
        "Cross-domain lower-level dependencies such as runtime → connection/logic are allowed when explicitly required.",
        "```",
        "",
        "## Architectural safeguards",
        "",
    ]
    combined_graph = {name: graph[name] | lazy_graph[name] for name in graph}
    forbidden = forbidden_edges(combined_graph)
    cycles = direct_cycles(graph)
    if forbidden:
        lines.append("**Forbidden upward dependencies detected:**")
        lines.extend(f"- `{src}` → `{dst}`" for src, dst in forbidden)
    else:
        lines.append("- ✅ No forbidden upward GUI dependencies detected.")
    if cycles:
        lines.append("- ⚠ Direct reciprocal import pairs: " + "; ".join(f"`{a}` ⇄ `{b}`" for a, b in cycles))
    else:
        lines.append("- ✅ No reciprocal direct production-module imports detected.")
    lines += ["", "# Folder map", ""] + tree_lines() + [""]

    # storage.py is a root package module and deserves an explicit section before folders.
    if "wayfinder.storage" in modules:
        info = modules["wayfinder.storage"]
        lines += ["# Root package services", ""]
        append_module(lines, info, graph, externals, lazy_graph, lazy_externals, reverse, lazy_reverse)

    for section_prefix, section_title in SECTION_ORDER:
        lines += [f"# `{section_prefix}` — {section_title}", ""]
        if section_prefix == "wayfinder/app/":
            # Preserve useful subpackage grouping for app.
            app_groups = [
                ("wayfinder/app/", None),
                ("wayfinder/app/core/", PACKAGE_PURPOSES["wayfinder/app/core/"]),
                ("wayfinder/app/controllers/", PACKAGE_PURPOSES["wayfinder/app/controllers/"]),
                ("wayfinder/app/pages/", PACKAGE_PURPOSES["wayfinder/app/pages/"]),
                ("wayfinder/app/ui/", PACKAGE_PURPOSES["wayfinder/app/ui/"]),
                ("wayfinder/app/map/", PACKAGE_PURPOSES["wayfinder/app/map/"]),
            ]
            emitted = set()
            for path_prefix, title in app_groups:
                if title:
                    lines += [f"## `{path_prefix}` — {title}", ""]
                candidates = [m for m in modules.values() if str(m.relative_path).replace('\\','/').startswith(path_prefix)]
                if path_prefix == "wayfinder/app/":
                    candidates = [m for m in candidates if len(m.relative_path.parts) == 3]
                else:
                    base_depth = len(Path(path_prefix).parts)
                    candidates = [m for m in candidates if len(m.relative_path.parts) == base_depth + 1]
                for info in sorted(candidates, key=lambda m: str(m.relative_path)):
                    if info.name not in emitted:
                        append_module(lines, info, graph, externals, lazy_graph, lazy_externals, reverse, lazy_reverse)
                        emitted.add(info.name)
        else:
            prefix_path = section_prefix.rstrip("/")
            candidates = [m for m in modules.values() if str(m.relative_path).replace('\\','/').startswith(prefix_path + "/")]
            base_depth = len(Path(prefix_path).parts)
            candidates = [m for m in candidates if len(m.relative_path.parts) == base_depth + 1]
            for info in sorted(candidates, key=lambda m: str(m.relative_path)):
                append_module(lines, info, graph, externals, lazy_graph, lazy_externals, reverse, lazy_reverse)

    lines += [
        "# Root-level files",
        "",
        "- `run_wayfinder.py` — primary Python entrypoint and role dispatcher.",
        "- `run_pytests.py` — repository test runner with per-file output.",
        "- `requirements.txt` — runtime Python dependencies.",
        "- `BUILD-SINGLE-EXE.bat` — Windows executable build helper.",
        "- `tools/generate_project_structure.py` — regenerates this document from the real source/import graph.",
        "",
        "# Dependency interpretation legend",
        "",
        "- **A → B**: A imports/uses B directly; B does not directly import A.",
        "- **A ⇄ B**: reciprocal direct imports; avoid because import order/test isolation become fragile.",
        "- **Implicit GUI coupling**: mixins can call methods/read state supplied by another mixin through `WayFinderApp` even without a Python import edge.",
        "- **Composition dependency**: `app.py` intentionally imports many components because it assembles the application; those components should not import `app.py` back.",
        "",
        "# Regeneration",
        "",
        "Run `python tools/generate_project_structure.py --check` to verify the document is current, or run it without `--check` to rewrite `PROJECT_STRUCTURE.md`.",
        "",
    ]
    return "\n".join(lines)


def append_module(lines: list[str], info: ModuleInfo, graph: dict[str, set[str]], externals: dict[str, set[str]], lazy_graph: dict[str, set[str]], lazy_externals: dict[str, set[str]], reverse: dict[str, set[str]], lazy_reverse: dict[str, set[str]]) -> None:
    """Handle append module."""
    lines += [
        f"### `{info.relative_path.as_posix()}`",
        f"# {purpose_for(info)}",
        f"- **Module:** `{info.name}`",
        f"- **Exports:** {fmt_names(exports_for(info), '_No declared public definitions/constants detected._')}",
        f"- **Import-time internal imports:** {fmt_names(graph[info.name], '_None._')}",
        f"- **Lazy/local internal imports:** {fmt_names(lazy_graph[info.name], '_None._')}",
        f"- **External / standard-library imports:** {fmt_names(externals[info.name] | lazy_externals[info.name], '_None._')}",
        f"- **Import-time importers:** {fmt_names(reverse.get(info.name, set()), '_No import-time production-module importers detected._')}",
        f"- **Lazy/local importers:** {fmt_names(lazy_reverse.get(info.name, set()), '_None._')}",
        f"- **Dependency direction:** {dependency_direction(info.name, graph, lazy_graph)}",
        "",
    ]

def main() -> int:
    """Handle main."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="Fail if PROJECT_STRUCTURE.md is stale or architecture rules are violated.")
    args = parser.parse_args()
    rendered = generate()
    modules = production_modules()
    names = set(modules)
    parsed = {name: imports_for(info, names) for name, info in modules.items()}
    combined = {name: values[0] | values[2] for name, values in parsed.items()}
    violations = forbidden_edges(combined)
    if violations:
        print("Forbidden architecture dependencies:")
        for source, dep in violations:
            print(f"  {source} -> {dep}")
        return 2
    if args.check:
        current = OUTPUT.read_text(encoding="utf-8") if OUTPUT.exists() else ""
        if current != rendered:
            print("PROJECT_STRUCTURE.md is stale. Run: python tools/generate_project_structure.py")
            return 1
        print("PROJECT_STRUCTURE.md is current and architecture rules pass.")
        return 0
    OUTPUT.write_text(rendered, encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
