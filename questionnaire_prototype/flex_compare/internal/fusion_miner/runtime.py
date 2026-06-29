from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Mapping, Sequence


from flex_compare.internal.shared.paths import PROJECT_ROOT

PACKAGE_ROOT = Path(__file__).resolve().parent
PROM_ROOT = PROJECT_ROOT / "tools" / "ProM"
PROM_PACKAGES_DIR = PROM_ROOT / "packages"
PROM_PACKAGES_XML = PROM_PACKAGES_DIR / "packages.xml"
PROM_DIST_DIR = PROM_ROOT / "dist"
PROM_LIB_DIR = PROM_ROOT / "lib"
JAVA_SRC_DIR = PACKAGE_ROOT / "java" / "src" / "main" / "java"
JAVA_BUILD_DIR = PACKAGE_ROOT / "java" / "build" / "classes"
LOCK_PATH = PACKAGE_ROOT / "prom-lock.json"
VENDOR_DIR = PACKAGE_ROOT / "vendor" / "prom-packages"
_LPSOLVE_ARM64_NATIVE_DIR = PACKAGE_ROOT / "java" / "native" / "lpsolve-macos-arm64"
_LPSOLVE_HOMEBREW_LIB_DIR = Path("/opt/homebrew/opt/lp_solve/lib")
LPSOLVE_NATIVE_DIR = _LPSOLVE_ARM64_NATIVE_DIR
LPSOLVE_LIBRARY_PATHS = tuple(
    path
    for path in (LPSOLVE_NATIVE_DIR, _LPSOLVE_HOMEBREW_LIB_DIR)
    if path.exists()
)

PROM_VERSION = "6.15"
CANONICAL_JAVA_SERIES = "11"
FACADE_MAIN_CLASS = "thesis.fusion.HeadlessFusionMinerFulRunner"
FUSION_ROOT_PACKAGES: tuple[str, ...] = ("FusionMinerFul", "DeclareMinerFul")
CORE_DIST_PACKAGES: tuple[str, ...] = (
    "ProM-Framework",
    "ProM-Contexts",
    "ProM-Models",
    "ProM-Plugins",
)


@dataclass(frozen=True)
class PackageInfo:
    name: str
    version: str
    url: str
    dependencies: tuple[str, ...]
    local_dir: Path | None


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _normalize_package_dir_name(name: str) -> str:
    return name.lower().replace("_", "-")


def _scan_local_package_dirs() -> Dict[str, Path]:
    local_dirs: Dict[str, Path] = {}
    if not PROM_PACKAGES_DIR.exists():
        return local_dirs
    for child in PROM_PACKAGES_DIR.iterdir():
        if not child.is_dir():
            continue
        stem = child.name
        if "-" not in stem:
            continue
        package_name = stem.rsplit("-", 1)[0]
        local_dirs[package_name.lower()] = child
    return local_dirs


def _load_package_index() -> Dict[str, PackageInfo]:
    if not PROM_PACKAGES_XML.exists():
        raise FileNotFoundError(f"ProM package index not found: {PROM_PACKAGES_XML}")

    root = ET.parse(PROM_PACKAGES_XML).getroot()
    local_dirs = _scan_local_package_dirs()
    packages: Dict[str, PackageInfo] = {}
    for package in root.iter("package"):
        name = package.attrib["name"]
        version = package.attrib.get("version", "unknown")
        url = package.attrib.get("url", "")
        dependencies = tuple(
            dependency.attrib["name"]
            for dependency in package.findall("dependency")
            if dependency.attrib.get("name")
        )
        local_dir = local_dirs.get(_normalize_package_dir_name(name))
        packages[name] = PackageInfo(
            name=name,
            version=version,
            url=url,
            dependencies=dependencies,
            local_dir=local_dir,
        )
    return packages


def resolve_dependency_closure(root_packages: Sequence[str] | None = None) -> Dict[str, PackageInfo]:
    packages = _load_package_index()
    requested = list(root_packages or FUSION_ROOT_PACKAGES)
    seen: Dict[str, PackageInfo] = {}
    stack = requested[:]
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        info = packages.get(current)
        if info is None:
            continue
        seen[current] = info
        stack.extend(dependency for dependency in info.dependencies if dependency not in seen)
    for core_name in CORE_DIST_PACKAGES:
        info = packages.get(core_name)
        if info is not None:
            seen[core_name] = info
    return dict(sorted(seen.items()))


def _iter_jar_files(base_dir: Path) -> Iterator[Path]:
    if not base_dir.exists():
        return
    for jar_path in sorted(base_dir.rglob("*.jar")):
        if jar_path.is_file():
            yield jar_path


def build_runtime_jars(root_packages: Sequence[str] | None = None) -> List[Path]:
    closure = resolve_dependency_closure(root_packages)
    jars: list[Path] = []

    for dist_name in CORE_DIST_PACKAGES:
        version = closure.get(dist_name).version if dist_name in closure else None
        if version:
            dist_jar = PROM_DIST_DIR / f"{dist_name}-{version}.jar"
            if dist_jar.exists():
                jars.append(dist_jar)

    jars.extend(_iter_jar_files(PROM_LIB_DIR))

    for package in closure.values():
        if package.local_dir is None:
            continue
        jars.extend(_iter_jar_files(package.local_dir))

    seen: set[Path] = set()
    unique: list[Path] = []
    for path in jars:
        resolved = path.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        unique.append(resolved)
    return unique


def build_runtime_classpath(root_packages: Sequence[str] | None = None) -> str:
    # Put locally compiled classes first so targeted hotfix classes can override
    # buggy implementations shipped by ProM packages.
    parts = [str(JAVA_BUILD_DIR.resolve())]
    parts.extend(str(path) for path in build_runtime_jars(root_packages))
    return os.pathsep.join(parts)


def select_java_binaries() -> Dict[str, Any]:
    candidates = [
        Path("/opt/homebrew/opt/openjdk@11/bin/java"),
        Path("/opt/homebrew/opt/openjdk@11/bin/javac"),
    ]
    java = Path("/opt/homebrew/opt/openjdk@11/bin/java")
    javac = Path("/opt/homebrew/opt/openjdk@11/bin/javac")
    if not java.exists():
        found_java = shutil.which("java")
        if found_java is None:
            raise FileNotFoundError("No Java runtime found.")
        java = Path(found_java)
    if not javac.exists():
        found_javac = shutil.which("javac")
        if found_javac is None:
            raise FileNotFoundError("No Java compiler found.")
        javac = Path(found_javac)

    version = subprocess.run(
        [str(java), "-version"],
        capture_output=True,
        text=True,
        check=False,
    )
    version_text = (version.stderr or version.stdout).strip()
    return {
        "java": java,
        "javac": javac,
        "version_text": version_text,
        "series": CANONICAL_JAVA_SERIES if "11." in version_text or ' "11' in version_text else "other",
    }


def compile_java_facade(force: bool = False) -> Path:
    source_files = sorted(JAVA_SRC_DIR.rglob("*.java"))
    if not source_files:
        raise FileNotFoundError(f"No Java facade sources found under {JAVA_SRC_DIR}")

    JAVA_BUILD_DIR.mkdir(parents=True, exist_ok=True)
    target_class = JAVA_BUILD_DIR / "thesis" / "fusion" / "HeadlessFusionMinerFulRunner.class"
    if not force and target_class.exists():
        latest_source = max(path.stat().st_mtime for path in source_files)
        if target_class.stat().st_mtime >= latest_source:
            return target_class

    java_bins = select_java_binaries()
    classpath = build_runtime_classpath()
    cmd = [
        str(java_bins["javac"]),
        "-source",
        "11",
        "-target",
        "11",
        "-cp",
        classpath,
        "-d",
        str(JAVA_BUILD_DIR),
    ]
    cmd.extend(str(path) for path in source_files)
    subprocess.run(cmd, check=True, cwd=PROJECT_ROOT)
    return target_class


def _download_with_curl(url: str, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        ["curl", "-L", "--fail", "--silent", "--show-error", "-o", str(target), url],
        check=True,
    )


def ensure_vendor_archives(
    root_packages: Sequence[str] | None = None,
    *,
    download_missing: bool = False,
) -> List[Dict[str, Any]]:
    closure = resolve_dependency_closure(root_packages)
    VENDOR_DIR.mkdir(parents=True, exist_ok=True)
    archived_packages: list[Dict[str, Any]] = []
    for package in closure.values():
        archive_name = Path(package.url).name if package.url else f"{package.name}-{package.version}.zip"
        archive_path = VENDOR_DIR / archive_name
        downloaded = False
        error: str | None = None
        if download_missing and package.url and not archive_path.exists():
            try:
                _download_with_curl(package.url, archive_path)
                downloaded = True
            except Exception as exc:  # pragma: no cover - network-dependent path
                error = str(exc)
        sha256 = _sha256(archive_path) if archive_path.exists() else None
        archived_packages.append(
            {
                "name": package.name,
                "version": package.version,
                "url": package.url,
                "archive_path": str(archive_path),
                "archive_exists": archive_path.exists(),
                "archive_downloaded_now": downloaded,
                "archive_sha256": sha256,
                "archive_error": error,
                "archive_expected_but_missing": bool(download_missing and package.url and not archive_path.exists()),
                "local_dir": str(package.local_dir) if package.local_dir else None,
            }
        )
    return archived_packages


def build_prom_lock(
    root_packages: Sequence[str] | None = None,
    *,
    download_missing_archives: bool = False,
) -> Dict[str, Any]:
    closure = resolve_dependency_closure(root_packages)
    java_bins = select_java_binaries()
    lock_packages = ensure_vendor_archives(
        root_packages,
        download_missing=download_missing_archives,
    )
    jars = build_runtime_jars(root_packages)
    return {
        "prom_version": PROM_VERSION,
        "canonical_java_series": CANONICAL_JAVA_SERIES,
        "java_runtime": str(java_bins["java"]),
        "java_compiler": str(java_bins["javac"]),
        "java_version_text": java_bins["version_text"],
        "root_packages": list(root_packages or FUSION_ROOT_PACKAGES),
        "core_dist_packages": list(CORE_DIST_PACKAGES),
        "vendor_archives_hydrated": all(
            package["archive_exists"] or not package["url"]
            for package in lock_packages
        ),
        "vendor_archives_download_attempted": download_missing_archives,
        "resolved_packages": [
            {
                "name": package.name,
                "version": package.version,
                "url": package.url,
                "dependencies": list(package.dependencies),
                "local_dir": str(package.local_dir) if package.local_dir else None,
            }
            for package in closure.values()
        ],
        "vendor_packages": lock_packages,
        "runtime_classpath_jars": [str(path) for path in jars],
    }


def materialize_prom_lock(
    lock_path: Path | None = None,
    *,
    download_missing_archives: bool = False,
) -> Dict[str, Any]:
    lock = build_prom_lock(download_missing_archives=download_missing_archives)
    path = lock_path or LOCK_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(lock, indent=2, ensure_ascii=False), encoding="utf-8")
    return lock


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Materialize the FusionMINERful ProM runtime lock."
    )
    parser.add_argument(
        "--download-archives",
        action="store_true",
        help="Download missing ProM package archives into vendor/prom-packages.",
    )
    args = parser.parse_args()

    lock = materialize_prom_lock(download_missing_archives=args.download_archives)
    print(LOCK_PATH)
    if args.download_archives and not lock.get("vendor_archives_hydrated", False):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
