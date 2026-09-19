"""Wheel-only dependency installation; never executes package build/install code.

HTTP, caching and ZIP handling use the standard library. The already bundled
packaging library implements PEP 440/508 and interpreter compatibility tags.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import importlib
import io
import json
import os
import re
import shutil
import stat
import sys
import tempfile
import zipfile
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from .source_recipes import source_candidate, source_payload, source_matches
from .bundled_wheels import remote_candidates

from packaging.markers import default_environment
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.tags import sys_tags
from packaging.utils import canonicalize_name, parse_wheel_filename
from packaging.version import Version, InvalidVersion


class InstallError(RuntimeError):
    """Actionable dependency failure safe to show in the setup report."""


class ResolutionError(InstallError):
    """A candidate branch cannot be satisfied; older releases may still work."""


class FileRequirement(Requirement):
    """A PEP 508 requirement with a requirements-file artifact allowlist."""
    __slots__ = ('allowed_hashes',)


def read_requirements(path, stack=()):
    """Read PEP 508 lines and relative -r/-c includes, rejecting unknown options."""
    path = Path(path).resolve()
    if path in stack:
        raise InstallError(f"Requirements include cycle: {path}")
    requirements, constraints = [], []
    text = path.read_text(encoding="utf-8-sig").replace("\\\n", "")
    for raw in text.splitlines():
        line = re.split(r"\s+#", raw, maxsplit=1)[0].strip()
        if not line or line.startswith("#"):
            continue
        match = re.match(r"^(--requirement|--constraint|-r|-c)(?:\s+|=)?(.+)$", line)
        if match:
            option, include = match.groups()
            child, limits = read_requirements(path.parent / include.strip(), (*stack, path))
            (constraints if option in ("-c", "--constraint") else requirements).extend(child)
            constraints.extend(limits)
        elif line.startswith("-"):
            raise InstallError(f"Unsupported requirements option in {path}: {line}")
        else:
            try:
                hashes = re.findall(r"(?:^|\s)--hash(?:=|\s+)sha256:([0-9a-fA-F]{64})(?=\s|$)", line)
                requirement_text = re.sub(r"\s+--hash(?:=|\s+)sha256:[0-9a-fA-F]{64}(?=\s|$)", "", line)
                requirement = FileRequirement(requirement_text)
                requirement.allowed_hashes = frozenset(h.lower() for h in hashes)
                requirements.append(requirement)
            except Exception as exc:
                raise InstallError(f"Invalid or unsupported requirement in {path}: {line}") from exc
    return requirements, constraints


def runtime_diagnostics(target):
    return {"mode": "Native wheel installer", "python": sys.executable,
            "ready": True, "system_python_required": not bool(getattr(sys, "frozen", False)),
            "system_pip_required": False, "target": str(target)}


class WheelInstaller:
    """Bounded backtracking resolver and transactional private-target installer."""

    def __init__(self, target, progress=None, tags=None, environment=None):
        self.target = Path(target).resolve()
        self.cache = self.target.parent / "wheel_cache"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.tags = {tag: i for i, tag in enumerate(tags if tags is not None else sys_tags())}
        self.environment = environment or default_environment()
        self.progress = progress or (lambda message: None)
        self.index = {}
        self.wheels = {}
        self.accepted = []
        self.accepted_constraints = []
        self._installed_signature = None
        # Candidates already materialized in the managed target during this run.
        # Later requirement units are cumulative, so unchanged wheels can be reused
        # instead of being written to disk again on every unit.
        self._installed_selected = {}

    def active(self, requirement, extras=()):
        return requirement.marker is None or any(
            requirement.marker.evaluate({**self.environment, "extra": extra})
            for extra in ("", *sorted(extras)))

    def fetch(self, url, limit):
        if urlsplit(url).scheme != "https":
            raise InstallError("Downloads must use HTTPS")
        try:
            with urlopen(Request(url, headers={"User-Agent": "WayFinder/1.0 wheel-installer"}), timeout=30) as response:
                if urlsplit(response.url).scheme != "https":
                    raise InstallError("Insecure download redirect")
                chunks, size = [], 0
                while chunk := response.read(1024 * 1024):
                    size += len(chunk)
                    if size > limit:
                        raise InstallError("Download exceeds size limit")
                    chunks.append(chunk)
                return b"".join(chunks)
        except (OSError, ValueError) as exc:
            raise InstallError(f"Network/download failure for {url}: {exc}") from exc

    def candidates(self, name, requirements):
        if name in {"pip", "uv"}:
            raise ResolutionError(f"Package installer dependency unsupported: {name}; WayFinder only installs runtime libraries")
        native = remote_candidates(name, requirements, self.tags)
        if native is not None:
            return [candidate for candidate in native if self.satisfies(candidate, requirements)]
        if any(r.url for r in requirements):
            entry = source_candidate(name, requirements)
            if entry is not None:
                if not SpecifierSet(entry['recipe']['python']).contains(self.environment['python_full_version'], prereleases=True):
                    return []
                version = Version(entry['recipe']['version'])
                return [(version, 0, entry)] if self.satisfies((version, 0, entry), requirements) else []
            raise ResolutionError(f"Source/direct URL dependency unsupported: {name}. Publish a compatible wheel on PyPI and update the world's requirement; source builds and Git installs are not supported.")
        if name not in self.index:
            self.progress(f"Resolving {name}")
            self.index[name] = json.loads(self.fetch(f"https://pypi.org/pypi/{name}/json", 32 * 1024 * 1024))
        candidates = []
        for version_text, files in self.index[name].get("releases", {}).items():
            try:
                version = Version(version_text)
            except InvalidVersion:
                continue
            if not all(r.specifier.contains(version) for r in requirements):
                continue
            for entry in files:
                if entry.get("yanked"):
                    continue
                if not SpecifierSet(entry.get("requires_python") or "").contains(self.environment["python_full_version"], prereleases=True):
                    continue
                if entry.get('packagetype') == 'sdist':
                    audited = source_candidate(name, requirements)
                    if (audited and audited['recipe'].get('archive_format') == 'tar.gz'
                            and audited['recipe']['version'] == version_text
                            and audited['digests'] == {'sha256': entry.get('digests', {}).get('sha256')}
                            and audited['url'] == entry.get('url')
                            and self.satisfies((version, -100000, audited), requirements)):
                        candidates.append((version, -100000, audited))
                    continue
                if entry.get('packagetype') != 'bdist_wheel':
                    continue
                try:
                    wheel_name, wheel_version, _, tags = parse_wheel_filename(entry["filename"])
                except ValueError:
                    continue
                ranks = [self.tags[t] for t in tags if t in self.tags]
                if ranks and wheel_name == name and wheel_version == version:
                    candidate = (version, -min(ranks), entry)
                    if self.satisfies(candidate, requirements):
                        candidates.append(candidate)
        return sorted(candidates, key=lambda c: (c[0], c[1]), reverse=True)

    @staticmethod
    def satisfies(candidate, requirements):
        version, _, entry = candidate
        for req in requirements:
            if req.url and not source_matches(entry, req.url):
                return False
            if not req.specifier.contains(version, prereleases=True if req.url else None):
                return False
            hashes = getattr(req, 'allowed_hashes', ())
            if hashes and entry.get('digests', {}).get('sha256') not in hashes:
                return False
        return True

    def wheel(self, entry):
        digest = entry.get("digests", {}).get("sha256", "")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise InstallError("PyPI did not provide a valid SHA256 digest")
        if digest in self.wheels:
            return self.wheels[digest]
        extension = ('.tar.gz' if entry.get('recipe', {}).get('archive_format') == 'tar.gz'
                     else '.zip' if 'recipe' in entry else '.whl')
        path = self.cache / (digest + extension)
        if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            path.unlink()
        if not path.exists():
            self.progress(f"Downloading {entry['filename']}")
            data = self.fetch(entry["url"], 256 * 1024 * 1024)
            if hashlib.sha256(data).hexdigest() != digest:
                raise InstallError(f"SHA256 mismatch: {entry['filename']}")
            with tempfile.NamedTemporaryFile(dir=self.cache, delete=False) as stream:
                temporary = Path(stream.name)
                stream.write(data)
            try:
                os.replace(temporary, path)
            finally:
                temporary.unlink(missing_ok=True)
        else:
            self.progress(f"Using cached {entry['filename']}")
        files, metadata = (source_payload(path, entry, self.safe_path) if 'recipe' in entry
                           else self.validate(path, entry["filename"]))
        self.wheels[digest] = (files, metadata)
        return files, metadata

    @staticmethod
    def safe_path(name):
        parts = PurePosixPath(name).parts
        if not parts or any(p in ("", ".", "..") for p in name.split("/")) or name.startswith("/") or "\\" in name or any(
            p in (".", "..") or ":" in p or p.endswith((".", " ")) or
            re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", p)
            for p in parts):
            raise InstallError(f"Unsafe wheel path: {name}")
        return parts

    def validate(self, path, filename):
        """Verify ZIP members, RECORD hashes, identity and supported wheel scheme."""
        expected_name, expected_version, _, _ = parse_wheel_filename(filename)
        with zipfile.ZipFile(path) as archive:
            members = [i for i in archive.infolist() if not i.is_dir()]
            if sum(i.file_size for i in members) > 512 * 1024 * 1024:
                raise InstallError("Expanded wheel exceeds size limit")
            names = [i.filename for i in members]
            if len({n.casefold() for n in names}) != len(names):
                raise InstallError("Duplicate wheel paths")
            for info in members:
                self.safe_path(info.filename)
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise InstallError("Wheel symlinks are unsupported")
            metadata_names = [n for n in names if re.fullmatch(r"[^/]+\.dist-info/METADATA", n)]
            if len(metadata_names) != 1:
                raise InstallError("Wheel must contain exactly one METADATA")
            dist = metadata_names[0].split("/")[0]
            dist_name, separator, dist_version = dist[:-10].rpartition("-")
            if not separator or canonicalize_name(dist_name) != expected_name or Version(dist_version) != expected_version:
                raise InstallError("Wheel dist-info identity mismatch")
            if any(n.split("/")[0].endswith(".dist-info") and not n.startswith(dist + "/") for n in names):
                raise InstallError("Multiple wheel dist-info directories")
            metadata = BytesParser().parsebytes(archive.read(metadata_names[0]))
            if canonicalize_name(metadata["Name"] or "") != expected_name or Version(metadata["Version"] or "0") != expected_version:
                raise InstallError("Wheel metadata identity mismatch")
            if not SpecifierSet(metadata.get("Requires-Python", "")).contains(self.environment["python_full_version"], prereleases=True):
                raise InstallError("Wheel Requires-Python excludes this interpreter")
            wheel = BytesParser().parsebytes(archive.read(dist + "/WHEEL"))
            if wheel.get("Wheel-Version") != "1.0":
                raise InstallError("Unsupported Wheel-Version")
            if dist + "/entry_points.txt" in names:
                self.progress(f"{expected_name}: installing library entry-point metadata; command-line launchers are not generated")
            record_name = dist + "/RECORD"
            rows = list(csv.reader(io.StringIO(archive.read(record_name).decode("utf-8"))))
            # Some Windows wheel producers serialize RECORD paths with backslashes.
            # Normalize only metadata paths, then apply the same traversal checks.
            records = {row[0].replace('\\', '/'): row[1:] for row in rows if len(row) == 3}
            if len(records) != len(rows):
                raise InstallError("Invalid or duplicate RECORD entries")
            for record_path in records:
                self.safe_path(record_path)
            if set(records) - set(names):
                raise InstallError("RECORD refers to absent wheel members")
            files = {}
            for name in names:
                if name in (record_name + ".jws", record_name + ".p7s"):
                    continue  # RECORD is rewritten after relocation, invalidating signatures.
                data = archive.read(name)
                if name not in (record_name, record_name + ".jws", record_name + ".p7s"):
                    digest, size = records.get(name, ("", ""))
                    algorithm, _, encoded = digest.partition("=")
                    if algorithm not in ("sha256", "sha384", "sha512"):
                        raise InstallError(f"Missing/unsupported RECORD hash: {name}")
                    actual = base64.urlsafe_b64encode(hashlib.new(algorithm, data).digest()).rstrip(b"=").decode()
                    if encoded != actual or size != str(len(data)):
                        raise InstallError(f"RECORD verification failed: {name}")
                parts = self.safe_path(name)
                if parts[0].endswith(".data"):
                    if len(parts) < 3 or parts[1] not in ("purelib", "platlib", "data", "scripts", "headers"):
                        raise InstallError(f"Unsupported wheel installation scheme: {name}")
                    if parts[1] == 'scripts':
                        # Preserve scripts without executing or advertising launchers.
                        name = 'Scripts/' + '/'.join(parts[2:])
                    elif parts[1] == 'headers':
                        name = 'Include/' + str(expected_name) + '/' + '/'.join(parts[2:])
                    else:
                        name = "/".join(parts[2:])
                if name.casefold() in {p.casefold() for p in files}:
                    raise InstallError(f"Wheel destination collision: {name}")
                files[name] = data
            # Rewrite RECORD for relocated .data members, preserving valid metadata.
            files[dist + "/INSTALLER"] = b"wayfinder-native-wheel\n"
            stream = io.StringIO(newline="")
            writer = csv.writer(stream)
            for name, data in sorted(files.items()):
                if name == record_name:
                    continue
                digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                writer.writerow((name, "sha256=" + digest, len(data)))
            writer.writerow((record_name, "", ""))
            files[record_name] = stream.getvalue().encode()
            return files, metadata

    def resolve(self, roots, constraints):
        """Recompute closure on every branch so backtracking drops stale edges."""
        attempts = 0
        last_error = "Dependency conflict"

        # A missing root can never be fixed by trying other versions of unrelated
        # packages. Diagnose it before exploring their entire transitive graphs.
        root_groups = {}
        for req in roots:
            if self.active(req):
                root_groups.setdefault(canonicalize_name(req.name), []).append(req)
        for req in constraints:
            name = canonicalize_name(req.name)
            if name in root_groups and self.active(req):
                root_groups[name].append(req)
        for name, requirements in root_groups.items():
            try:
                options = self.candidates(name, requirements)
            except ResolutionError as exc:
                raise InstallError(str(exc)) from exc
            if not options:
                category = 'Dependency conflict or unavailable artifact' if len(requirements) > 1 else 'No compatible wheel'
                detail = ' Requirement SHA256 allowlists are enforced.' if any(getattr(r, 'allowed_hashes', ()) for r in requirements) else ''
                raise InstallError(f'{category}: {name}: ' + ', '.join(map(str, requirements))
                                   + '. No supported artifact matches this Python/platform and requirement set.' + detail)

        def search(selected):
            nonlocal attempts, last_error
            attempts += 1
            if attempts > 2000:
                raise InstallError("Dependency resolution limit reached; simplify or pin the world's requirements")
            requirements = {}
            pending = [r for r in roots if self.active(r)]
            expanded = {}
            while pending:
                req = pending.pop()
                name = canonicalize_name(req.name)
                entries = requirements.setdefault(name, [])
                identity = lambda r: (str(r), tuple(sorted(getattr(r, 'allowed_hashes', ()))))
                if identity(req) not in {identity(r) for r in entries}:
                    entries.append(req)
                if name in selected:
                    extras = frozenset(e for r in entries for e in r.extras)
                    if expanded.get(name) != extras:
                        expanded[name] = extras
                        metadata = self.wheel(selected[name][2])[1]
                        for value in metadata.get_all("Requires-Dist", []):
                            child = Requirement(value)
                            if self.active(child, extras):
                                pending.append(child)
            for req in constraints:
                name = canonicalize_name(req.name)
                if name in requirements and self.active(req):
                    requirements[name].append(req)
            for name, candidate in selected.items():
                if name in requirements and not self.satisfies(candidate, requirements[name]):
                    last_error = f"Dependency conflict: {name}: " + ", ".join(map(str, requirements[name]))
                    return None
            missing = next((n for n in requirements if n not in selected), None)
            if missing is None:
                return {n: c for n, c in selected.items() if n in requirements}
            try:
                options = self.candidates(missing, requirements[missing])
            except ResolutionError as exc:
                last_error = str(exc)
                return None
            if not options:
                last_error = f"No compatible wheel for {missing} ({', '.join(map(str, requirements[missing]))}) on Python {self.environment['python_full_version']} / {self.environment['sys_platform']}. Source builds are not supported; ask the world/package maintainer for a compatible wheel."
                if len(requirements[missing]) > 1 and not any(r.url for r in requirements[missing]) and all(self.candidates(missing, [r]) for r in requirements[missing]):
                    last_error = f"Dependency conflict: {missing}: " + ", ".join(map(str, requirements[missing]))
                if any(getattr(r, 'allowed_hashes', ()) for r in requirements[missing]):
                    last_error += ' No candidate satisfies the declared version/platform and requirement SHA256 allowlist; hashes were not ignored.'
            for candidate in options:
                result = search({**selected, missing: candidate})
                if result is not None:
                    return result
            return None

        result = search({})
        if result is None:
            raise InstallError(last_error)
        return result

    def install(self, requirements, constraints=()):
        roots = self.accepted + list(requirements)
        limits = self.accepted_constraints + list(constraints)
        selected = self.resolve(roots, limits)
        signature = tuple(sorted((name, candidate[2]['digests']['sha256']) for name, candidate in selected.items()))
        if signature != self._installed_signature or not self.target.is_dir():
            self.commit(selected)
            self._installed_signature = signature
            self._installed_selected = dict(selected)
        else:
            self.progress('Resolved dependencies are already installed in this run')
        self.accepted, self.accepted_constraints = roots, limits

    def commit(self, selected):
        """Stage a complete generation then swap; keep old target on write failure.

        The target is exclusively managed by WayFinder. Rebuilding it removes
        obsolete versions/files, avoiding unsafe uninstall using old RECORD paths.
        """
        self.target.parent.mkdir(parents=True, exist_ok=True)
        lock = self.target.parent / ".wheel-install.lock"
        try:
            fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError as exc:
            raise InstallError("Another dependency install is active (or a stale .wheel-install.lock remains after a crash)") from exc
        os.close(fd)
        stage = Path(tempfile.mkdtemp(prefix=".wheel-stage-", dir=self.target.parent))
        backup = self.target.with_name(self.target.name + ".previous")
        try:
            if backup.exists():
                raise InstallError(f"Previous interrupted install requires recovery: {backup}. Close WayFinder and restore/remove this backup before retrying.")
            paths = {}
            for name, candidate in sorted(selected.items()):
                previous = self._installed_selected.get(name)
                unchanged = (
                    previous is not None
                    and previous[2]["digests"]["sha256"] == candidate[2]["digests"]["sha256"]
                    and self.target.is_dir()
                )
                if unchanged:
                    self.progress(f"Reusing {name} {candidate[0]}")
                else:
                    self.progress(f"Installing {name} {candidate[0]}")
                for relative, data in self.wheel(candidate[2])[0].items():
                    key = relative.casefold()
                    if key in paths and paths[key] != data:
                        raise InstallError(f"Conflicting wheel files: {relative}")
                    paths[key] = data
                    safe_relative = self.safe_path(relative)
                    destination = stage.joinpath(*safe_relative)
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    source = self.target.joinpath(*safe_relative)
                    if unchanged and source.is_file():
                        try:
                            # Stage unchanged files as hard links. The target and stage
                            # share a volume, so this avoids repeatedly rewriting large
                            # dependency trees while preserving the atomic directory swap.
                            os.link(source, destination)
                            continue
                        except OSError:
                            # Filesystems/security products can reject hard links; copying
                            # is still cheaper and safer than treating reuse as a failure.
                            try:
                                shutil.copy2(source, destination)
                                continue
                            except OSError:
                                pass
                    destination.write_bytes(data)
            if self.target.exists():
                self.target.rename(backup)
            try:
                stage.rename(self.target)
            except OSError:
                if backup.exists():
                    backup.rename(self.target)
                raise
            # A Windows process may still hold a native extension in the backup.
            # Retain it for explicit recovery if deletion cannot complete.
            if backup.exists():
                shutil.rmtree(backup, ignore_errors=True)
                if backup.exists():
                    self.progress(f"Installed; loaded files remain in {backup}. Close WayFinder and remove this backup before the next dependency install.")
            importlib.invalidate_caches()
        finally:
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            lock.unlink(missing_ok=True)
