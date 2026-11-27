"""Build the Linux AppImage: the portable Windows application, a pinned Wine build and a launcher.

Run from the repository root on Linux x86_64, after building the exporter (PowerShell runs on Linux too):
    pwsh scripts/build-exporter.ps1
    python3 scripts/package-appimage.py --output dist/evryBuild-x86_64.AppImage

The application folder is exactly what package-evrybuild.py makes for the Windows ZIP. With --release-tag it is the
release package, whose manifest lets the planner see newer releases; an AppImage never updates itself, since it is a
read-only image, so the planner then points to the new AppImage instead. Wine, appimagetool and the AppImage runtime
are downloaded once into --cache and used only if their SHA-256 matches the pin below.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import NamedTuple
import urllib.request


REPOSITORY = Path(__file__).resolve().parents[1]
FILES = REPOSITORY / "scripts/appimage"

_spec = importlib.util.spec_from_file_location("evrybuild_package", Path(__file__).with_name("package-evrybuild.py"))
package_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(package_module)
PackageError = package_module.PackageError


class Pin(NamedTuple):
    url: str
    sha256: str

    @property
    def name(self) -> str:
        return self.url.rsplit("/", 1)[1]


# Kron4ek's unpatched Wine 11.0 (stable). The wow64 build runs 64-bit Windows programs without 32-bit host libraries.
WINE = Pin("https://github.com/Kron4ek/Wine-Builds/releases/download/11.0/wine-11.0-amd64-wow64.tar.xz",
           "39574efa1132c3ca0d5c77dd2eddbe4a49cca0d6cc2c290ff4924493a1c40314")
WINE_ROOT = "wine-11.0-amd64-wow64"
APPIMAGETOOL = Pin("https://github.com/AppImage/appimagetool/releases/download/1.9.1/appimagetool-x86_64.AppImage",
                   "ed4ce84f0d9caff66f50bcca6ff6f35aae54ce8135408b3fa33abfc3cb384eb0")
# The static runtime: the AppImage needs FUSE 2 or 3, or none with --appimage-extract-and-run.
RUNTIME = Pin("https://github.com/AppImage/type2-runtime/releases/download/20251108/runtime-x86_64",
              "2fca8b443c92510f1483a883f60061ad09b46b978b2631c807cd873a47ec260d")

# Inside the AppImage. AppRun names the same folders.
APP_DIR = PurePosixPath("usr/lib/evryBuild/app")
WINE_DIR = PurePosixPath("usr/lib/evryBuild/wine")
DOC_DIR = PurePosixPath("usr/share/doc/evryBuild")
# Wine's programs that evryBuild or a user fixing the prefix can need; the rest are development tools.
WINE_PROGRAMS = {"wine", "wineserver", "wineboot", "winecfg", "winepath", "regedit", "msiexec", "wineconsole"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch(pin: Pin, cache: Path) -> Path:
    """The pinned file from the cache, downloading it first if needed. A file whose SHA-256 differs is never used."""
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / pin.name
    if target.is_file() and sha256_file(target) == pin.sha256:
        return target
    partial = cache / (pin.name + ".part")
    print(f"Downloading {pin.url}", file=sys.stderr)
    request = urllib.request.Request(pin.url, headers={"User-Agent": "evryBuild-package-appimage"})
    with urllib.request.urlopen(request, timeout=120) as response, partial.open("wb") as file:
        shutil.copyfileobj(response, file, 1024 * 1024)
    actual = sha256_file(partial)
    if actual != pin.sha256:
        partial.unlink()
        raise PackageError(f"{pin.name} has SHA-256 {actual}, not the pinned {pin.sha256}. Nothing was built.")
    os.replace(partial, target)
    return target


def wine_member(name: str) -> PurePosixPath | None:
    """Where a member of the Wine archive goes inside the Wine folder, or None to leave it out."""
    path = PurePosixPath(name)
    if not path.parts or path.parts[0] != WINE_ROOT or any(p in ("", ".", "..") for p in path.parts):
        raise PackageError(f"Unexpected path in the Wine archive: {name}")
    inner = PurePosixPath(*path.parts[1:]) if len(path.parts) > 1 else PurePosixPath(".")
    top = inner.parts[0] if inner.parts else ""
    if top in ("include",) or inner.parts[:2] in (("share", "man"), ("share", "applications")):
        return None
    if inner.parts[:3] == ("lib", "wine", "i386-windows"):
        return None   # 32-bit Windows libraries: evryBuild and its exporter are 64-bit.
    if top == "lib" and inner.suffix == ".a":
        return None   # Import libraries for building Windows programs.
    if top == "bin" and len(inner.parts) == 2 and inner.name not in WINE_PROGRAMS:
        return None
    return inner


def extract_wine(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    root = destination.resolve()
    with tarfile.open(archive) as tar:
        for member in tar:
            inner = wine_member(member.name)
            if inner is None or inner == PurePosixPath("."):
                continue
            if not (member.isdir() or member.isfile() or member.issym()):
                raise PackageError(f"Unexpected file type in the Wine archive: {member.name}")
            target = destination / inner
            if not target.resolve().is_relative_to(root):
                raise PackageError(f"Unexpected path in the Wine archive: {member.name}")
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if member.issym():
                link = PurePosixPath(member.linkname)
                if link.is_absolute() or not (target.parent / link).resolve().is_relative_to(root):
                    raise PackageError(f"A link in the Wine archive leaves Wine's folder: {member.name}")
                target.symlink_to(member.linkname)
                continue
            with tar.extractfile(member) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output, 1024 * 1024)
            target.chmod(0o755 if member.mode & 0o111 else 0o644)
            os.utime(target, (member.mtime, member.mtime))
    for program in ("wine", "wineserver"):
        if not (destination / "bin" / program).is_file():
            raise PackageError(f"The Wine archive has no bin/{program}.")


def build_appdir(source: Path, appdir: Path, wine_archive: Path, release) -> dict:
    """Lays out the AppImage's contents in appdir, which must not exist yet."""
    (appdir / APP_DIR).parent.mkdir(parents=True)
    result = package_module.package(source, appdir / APP_DIR, release)
    extract_wine(wine_archive, appdir / WINE_DIR)
    shutil.copyfile(FILES / "AppRun", appdir / "AppRun")
    (appdir / "AppRun").chmod(0o755)
    shutil.copyfile(FILES / "evryBuild.desktop", appdir / "evryBuild.desktop")
    shutil.copyfile(FILES / "evryBuild.png", appdir / "evryBuild.png")
    shutil.copyfile(FILES / "evryBuild.png", appdir / ".DirIcon")
    docs = appdir / DOC_DIR
    (docs / "wine").mkdir(parents=True)
    for notice in ("NOTICE-Wine.md", "WINE-LICENSE.txt", "WINE-COPYING.LIB.txt"):
        shutil.copyfile(FILES / "notices" / notice, docs / "wine" / notice)
    return result


def run_appimagetool(tool: Path, runtime: Path, appdir: Path, output: Path) -> None:
    tool.chmod(0o755)
    # appimagetool is itself an AppImage; extract-and-run needs no FUSE on the build machine.
    env = dict(os.environ, ARCH="x86_64", APPIMAGE_EXTRACT_AND_RUN="1")
    command = [str(tool), "--no-appstream", "--runtime-file", str(runtime), "--comp", "zstd",
               "--mksquashfs-opt", "-Xcompression-level", "--mksquashfs-opt", "19",
               "--mksquashfs-opt", "-b", "--mksquashfs-opt", "1M", str(appdir), str(output)]
    completed = subprocess.run(command, env=env, cwd=appdir.parent, capture_output=True, text=True)
    if completed.returncode != 0 or not output.is_file():
        raise PackageError("appimagetool failed:\n" + (completed.stdout + completed.stderr)[-4000:])


def build(source_root: Path, output: Path, cache: Path, release=None) -> dict:
    source = source_root.expanduser().resolve()
    target = output.expanduser().resolve()
    if target.suffix != ".AppImage":
        raise PackageError("The output must be a .AppImage file.")
    checksum = Path(str(target) + ".sha256")
    if target.exists() or output.is_symlink() or checksum.exists() or checksum.is_symlink():
        raise PackageError("The output or its .sha256 already exists. Choose a new file; existing files are never overwritten.")
    if not target.parent.is_dir():
        raise PackageError("The output's parent folder must already exist.")
    if target.is_relative_to(source / "src") or target.is_relative_to(source / "runtime"):
        raise PackageError("The output cannot be inside the application or runtime folders.")
    wine = fetch(WINE, cache)
    tool = fetch(APPIMAGETOOL, cache)
    runtime = fetch(RUNTIME, cache)
    with tempfile.TemporaryDirectory(prefix=".evrybuild-appimage-", dir=target.parent) as stage:
        appdir = Path(stage) / "evryBuild.AppDir"
        packaged = build_appdir(source, appdir, wine, release)
        partial = Path(stage) / target.name
        run_appimagetool(tool, runtime, appdir, partial)
        if target.exists():
            raise PackageError("The output appeared while building; it was not overwritten.")
        os.rename(partial, target)
    digest = sha256_file(target)
    checksum.write_text(f"{digest}  {target.name}\n", encoding="utf-8")
    return {"ok": True, "appImage": str(target), "sha256": digest, "bytes": target.stat().st_size,
            "version": packaged["version"], "sourceRevision": packaged["sourceRevision"],
            "wine": WINE.name, **({"tag": packaged["tag"]} if "tag" in packaged else {})}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--output", required=True, type=Path, help="New .AppImage file; a .sha256 file is written beside it")
    parser.add_argument("--source-root", type=Path, default=REPOSITORY, help="evryBuild checkout (default: this repository)")
    parser.add_argument("--release-tag", help="Package the release for this tag, as package-evrybuild.py does")
    parser.add_argument("--cache", type=Path, default=REPOSITORY / "dist/appimage-cache",
                        help="Folder for the pinned downloads (default: dist/appimage-cache)")
    args = parser.parse_args(argv)
    try:
        if sys.platform != "linux":
            raise PackageError("Build the AppImage on Linux x86_64.")
        release = package_module.parse_release(args.release_tag, None)
        print(json.dumps(build(args.source_root, args.output, args.cache, release), indent=2))
        return 0
    except (PackageError, OSError, ValueError, tarfile.TarError) as error:
        print(json.dumps({"ok": False, "error": str(error)}, indent=2), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
