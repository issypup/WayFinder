"""Resolve WayFinder-hosted native wheels without bundling them in the app.

The small trusted manifest is kept in code so dependency resolution works without
shipping wheel files.  Wheel payloads are downloaded on demand from WayFinder's
GitHub repository and are still verified by SHA-256 before installation.
"""
from packaging.utils import canonicalize_name, parse_wheel_filename
import re

from .source_recipes import source_matches

GITHUB_RAW_ROOT = "https://raw.githubusercontent.com/issypup/WayFinder/main/native_wheels"
NATIVE_NAMES = {"pyfastbti", "pyfasttextureutils", "pyfastyaz0yay0"}

# Trusted metadata for the release-built wheels hosted in the WayFinder repo.
# Keep this in sync with native_wheels/manifest.json when publishing new wheels.
_TRUSTED_WHEELS = (
    {
        "name": "pyfastbti",
        "version": "1.0",
        "filename": "pyfastbti-1.0-cp313-cp313-win_amd64.whl",
        "sha256": "9801edb6730a0560142892ffb78c8e94e73b5e56046b7e4e44357960dd104b87",
        "source": {
            "repo": "LagoLunatic/PyFastBTI",
            "commit": "13b24b028b62d199740044f15085f70878ea80a4",
            "revision": "13b24b028b62d199740044f15085f70878ea80a4",
            "version": "1.0",
            "sha256": "c87b4286d09a8043f985d02fde2021503e182244b19278d73c5962d67474c904",
        },
    },
    {
        "name": "pyfasttextureutils",
        "version": "1.0",
        "filename": "pyfasttextureutils-1.0-cp313-cp313-win_amd64.whl",
        "sha256": "3f647ac8dd3ba37003f426f6fac09257c512c284de9d88b3121b49a911edcebc",
        "source": {
            "repo": "LagoLunatic/PyFastTextureUtils",
            "commit": "ec40de927daa6b59485e34ea01b8bab1ecd1a31a",
            "revision": "ec40de927daa6b59485e34ea01b8bab1ecd1a31a",
            "version": "1.0",
            "sha256": "183f207d9e046dc2b2a728f9a3bbe1226af6a18c139921a78467c59234fac2b2",
        },
    },
    {
        "name": "pyfastyaz0yay0",
        "version": "2.0",
        "filename": "pyfastyaz0yay0-2.0-cp313-cp313-win_amd64.whl",
        "sha256": "fb9c545fda8ab935f26d33c6f3f2dc88c0fa75428c1600593199e603a4de7098",
        "source": {
            "repo": "LagoLunatic/PyFastYaz0Yay0",
            "commit": "2adb8a8c00d98f98f245e0304094a0610203a82e",
            "revision": "2adb8a8c00d98f98f245e0304094a0610203a82e",
            "version": "2.0",
            "sha256": "d65309d442bcdf9d1d384eef444fbbdea9fe5145f273d8ee67f3ec01fdb17b50",
        },
    },
)


def manifest_entries():
    """Return validated metadata for native wheels hosted by WayFinder."""
    entries = []
    for item in _TRUSTED_WHEELS:
        filename = item["filename"]
        if not re.fullmatch(r"[A-Za-z0-9_.+-]+\.whl", filename):
            raise ValueError("Unsafe native wheel filename in trusted metadata")
        name, version, _, tags = parse_wheel_filename(filename)
        if name != canonicalize_name(item["name"]) or str(version) != item["version"]:
            raise ValueError("Native wheel metadata identity mismatch")
        if not re.fullmatch(r"[0-9a-f]{64}", item["sha256"]):
            raise ValueError("Invalid native wheel checksum in trusted metadata")
        entries.append(dict(
            name=name,
            version=version,
            tags=tags,
            filename=filename,
            source=item["source"],
            url=f"{GITHUB_RAW_ROOT}/{filename}",
            digests={"sha256": item["sha256"]},
        ))
    return entries


def remote_candidates(name, requirements, tag_ranks):
    """Return compatible WayFinder-hosted native wheel candidates."""
    if name not in NATIVE_NAMES:
        return None
    candidates = []
    for entry in manifest_entries():
        if entry["name"] != name:
            continue
        if any(r.extras or (r.url and not source_matches(entry, r.url)) for r in requirements):
            continue
        ranks = [tag_ranks[t] for t in entry["tags"] if t in tag_ranks]
        if ranks:
            candidates.append((entry["version"], -min(ranks), entry))
    return candidates


def source_entry(name, requirement):
    """Return expected source identity for installed-provenance checks."""
    if name not in NATIVE_NAMES:
        return None
    return next((entry for entry in manifest_entries()
                 if entry["name"] == name and source_matches(entry, requirement.url)), None)
