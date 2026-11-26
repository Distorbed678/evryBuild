"""Focused release-packaging checks; no real game files or other installations are used."""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

spec = importlib.util.spec_from_file_location("evrybuild_package", Path(__file__).with_name("package-evrybuild.py"))
package_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package_module)
appimage_spec = importlib.util.spec_from_file_location("evrybuild_appimage", Path(__file__).with_name("package-appimage.py"))
appimage_module = importlib.util.module_from_spec(appimage_spec)
appimage_spec.loader.exec_module(appimage_module)
# The AppImage reuses the portable packager; share its module so a patch applies to both.
appimage_module.package_module = package_module
appimage_module.PackageError = package_module.PackageError


class PackageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="evrybuild-source-package-")
        self.folder = Path(self.temporary.name)
        self.source = self.folder / "source"
        self.source.mkdir()
        self.target = self.folder / "evryBuild"
        self.entries = [
            ("default", "LICENSE.md"), ("default", "help.txt"), ("default", "changelog.txt"),
            ("runtime", package_module.HOST), ("runtime", "lua51.dll"), ("runtime", "SimpleGraphic.dll"),
            ("runtime", "lcurl.dll"), ("runtime", "libcurl.dll"), ("runtime", "zlib1.dll"),
            ("runtime", "lua/dkjson.lua"), ("runtime", "lua/base64.lua"),
            ("runtime", "SimpleGraphic/Fonts/Vera.ttf"),
            ("program", "Launch.lua"), ("program", "GameVersions.lua"),
            ("program", "Modules/Main.lua"), ("program", "Classes/ImportTab.lua"),
            ("tree", "TreeData/3_29/tree.lua"),
        ]
        for part, name in self.entries:
            location = self.source / ({"default": "", "runtime": "runtime", "program": "src", "tree": "src"}[part]) / name
            location.parent.mkdir(parents=True, exist_ok=True)
            location.write_bytes(("current fork file: " + name).encode())
        (self.source / "src/Modules/LocalExile.lua").write_text("current fork integration", encoding="utf-8")
        (self.source / "runtime/msvcr100.dll").write_bytes(b"compatibility runtime")
        (self.source / "src/Modules/LocalExileNative.lua").write_text("local process bridge")
        (self.source / "README.md").write_text("Portable application quick start", encoding="utf-8")
        (self.source / "VERSION").write_text("1.1.0\n", encoding="utf-8")
        (self.source / "docs").mkdir()
        (self.source / "docs/LocalExile.md").write_text("Database export setup instructions", encoding="utf-8")
        (self.source / "docs/images").mkdir()
        (self.source / "docs/images/localexile-export.png").write_bytes(b"README screenshot fixture")
        (self.source / "docs/images/localexile-export-dialog.png").write_bytes(b"README dialog screenshot fixture")
        exporter = self.source / "runtime/LocalExile/evryBuild.Export.exe"
        exporter.parent.mkdir(parents=True)
        exporter.write_bytes(b"synthetic exporter runtime")
        (exporter.parent / "exporter-build.json").write_text(json.dumps({"sha256":hashlib.sha256(exporter.read_bytes()).hexdigest()}))
        notice = self.source / "tools/LocalExile.Export/NOTICE.md"
        notice.parent.mkdir(parents=True)
        notice.write_text("Exporter attribution")
        notices = notice.parent / 'notices'
        notices.mkdir()
        for name in ('DOTNET-LICENSE.txt', 'DOTNET-THIRD-PARTY-NOTICES.txt', 'SQLITEPCLRAW-LICENSE.txt'):
            (notices / name).write_text('Third-party license text')
        receipt = exporter.parent / "exporter-build.json"
        receipt.write_text(json.dumps({"sha256":hashlib.sha256(exporter.read_bytes()).hexdigest(),
                                      "sources":{p.relative_to(notice.parent).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                                                 for p in notice.parent.rglob('*') if p.is_file()}}))
        for name in ("Settings.xml", "LocalExile.json", "imgui.ini", "first.run", "installed.cfg", "Builds/Personal.xml", "Update/private.tmp"):
            path = self.source / "src" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("personal state", encoding="utf-8")
        self.write_manifest()

    def write_manifest(self):
        manifest = ET.Element("PoBVersion")
        ET.SubElement(manifest, "Version", number="2.67.2")
        for part, name in self.entries:
            ET.SubElement(manifest, "File", name=name, part=part, sha1="upstream-old-hash")
        ET.ElementTree(manifest).write(self.source / "manifest.xml", encoding="utf-8", xml_declaration=True)

    def tearDown(self):
        self.temporary.cleanup()

    def package(self):
        with patch.object(package_module, "source_revision", return_value="source-commit"):
            return package_module.package(self.source, self.target)

    def test_packages_current_fork_and_compiled_runtime_without_an_external_installation(self):
        before = {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*") if p.is_file()}
        changed = self.source / "src/Modules/Main.lua"
        changed.write_bytes(b"uncommitted fork source is the packaging input")
        before[changed.relative_to(self.source)] = changed.read_bytes()
        result = self.package()
        self.assertTrue(result["ok"])
        self.assertEqual((self.target / "evryBuild.exe").read_bytes(), (self.source / "runtime" / package_module.HOST).read_bytes())
        self.assertEqual((self.target / "Modules/Main.lua").read_bytes(), changed.read_bytes())
        self.assertEqual((self.target / "Modules/LocalExile.lua").read_text(), "current fork integration")
        self.assertTrue((self.target / "lua/dkjson.lua").is_file())
        self.assertTrue((self.target / "SimpleGraphic/Fonts/Vera.ttf").is_file())
        self.assertTrue((self.target / "LICENSE.md").is_file())
        self.assertTrue((self.target / "msvcr100.dll").is_file())
        self.assertFalse((self.target / package_module.HOST).exists())
        self.assertEqual(before, {p.relative_to(self.source): p.read_bytes() for p in self.source.rglob("*") if p.is_file()})

    def test_personal_profiles_downloads_and_unlisted_files_are_omitted(self):
        self.package()
        self.assertEqual([], list((self.target / "Builds").iterdir()))
        for name in ("Settings.xml", "LocalExile.json", "imgui.ini", "first.run", "installed.cfg", "Update"):
            self.assertFalse((self.target / name).exists(), name)
        release = ET.parse(self.target / "manifest.xml").getroot().find("Version")
        self.assertEqual("2.67.2", release.get("number"))
        self.assertEqual("win32", release.get("platform"))
        self.assertEqual("evrybuild", release.get("branch"))
        record = json.loads((self.target / "evryBuild-package.json").read_text())
        self.assertEqual("source-commit", record["sourceRevision"])
        self.assertTrue(record["portableUserData"])
        self.assertIn("Modules/LocalExile.lua", record["filesSha256"])
        self.assertIn('"%~dp0evryBuild.exe" "%~dp0Launch.lua"', (self.target / "evryBuild.cmd").read_text())

    def test_portable_includes_current_setup_instructions_and_refuses_missing_guide(self):
        guide = self.source / 'docs/LocalExile.md'
        expected = guide.read_bytes()
        guide.unlink()
        with self.assertRaisesRegex(package_module.PackageError, 'required application file'):
            self.package()
        self.assertFalse(self.target.exists())
        guide.write_bytes(expected)
        self.package()
        self.assertEqual(expected, (self.target / 'docs/LocalExile.md').read_bytes())
        self.assertEqual((self.source / 'README.md').read_bytes(), (self.target / 'README.md').read_bytes())
        record = json.loads((self.target / 'evryBuild-package.json').read_text())
        self.assertEqual(hashlib.sha256(expected).hexdigest(), record['filesSha256']['docs/LocalExile.md'])
        for screenshot in ('docs/images/localexile-export.png', 'docs/images/localexile-export-dialog.png'):
            self.assertEqual((self.source / screenshot).read_bytes(), (self.target / screenshot).read_bytes())
            self.assertEqual(hashlib.sha256((self.source / screenshot).read_bytes()).hexdigest(), record['filesSha256'][screenshot])

    def test_an_existing_application_or_profile_is_never_overwritten(self):
        self.target.mkdir()
        saved = self.target / "Settings.xml"
        saved.write_text("keep my profile")
        with self.assertRaisesRegex(package_module.PackageError, "already exists"):
            self.package()
        self.assertEqual("keep my profile", saved.read_text())

    def test_unsafe_source_overlap_is_refused_before_copying(self):
        for output in (self.source, self.source / "src/release", self.source / "runtime/release", self.folder):
            with self.subTest(output=output), self.assertRaisesRegex(package_module.PackageError, "source checkout"):
                package_module.package(self.source, output)

    def test_an_ignored_dist_directory_can_hold_a_new_release(self):
        dist = self.source / "dist"
        dist.mkdir()
        self.target = dist / "evryBuild"
        self.assertTrue(self.package()["ok"])

    def test_bad_manifest_paths_private_state_and_missing_files_stop_before_publication(self):
        for part, name in (("program", "../Settings.xml"), ("program", "Settings.xml"),
                           ("program", "/absolute.lua"), ("runtime", "C:/outside.dll"), ("program", "Unknown/private.lua")):
            self.entries.append((part, name))
            self.write_manifest()
            with self.subTest(name=name), self.assertRaises(package_module.PackageError):
                self.package()
            self.entries.pop()
            self.assertFalse(self.target.exists())
        self.write_manifest()
        (self.source / "runtime/lua51.dll").unlink()
        with self.assertRaisesRegex(package_module.PackageError, "required application file"):
            self.package()
        self.assertFalse(self.target.exists())

    def test_copy_failure_cleans_only_the_checked_staging_folder(self):
        original = package_module.shutil.copy2
        count = 0

        def fail_after_a_file(source, destination):
            nonlocal count
            count += 1
            if count == 2:
                raise OSError("synthetic copy failure")
            return original(source, destination)

        marker = self.folder / "keep.txt"
        marker.write_text("unrelated")
        with patch.object(package_module.shutil, "copy2", side_effect=fail_after_a_file):
            with self.assertRaisesRegex(OSError, "synthetic"):
                self.package()
        self.assertFalse(self.target.exists())
        self.assertEqual([], list(self.folder.glob(".evrybuild-package-*")))
        self.assertEqual("unrelated", marker.read_text())

    def test_omitted_required_integration_and_output_collisions_are_rejected(self):
        (self.source / "src/Modules/LocalExile.lua").unlink()
        with self.assertRaisesRegex(package_module.PackageError, "required application file"):
            self.package()
        (self.source / "src/Modules/LocalExile.lua").write_text("module")
        self.entries.append(("program", "Launch.lua"))
        self.write_manifest()
        with self.assertRaisesRegex(package_module.PackageError, "overwrite"):
            self.package()

    def test_stale_exporter_and_changed_source_are_refused(self):
        exporter = self.source / 'runtime/LocalExile/evryBuild.Export.exe'
        original = exporter.read_bytes()
        exporter.write_bytes(b'changed executable')
        with self.assertRaisesRegex(package_module.PackageError, 'build receipt'):
            self.package()
        exporter.write_bytes(original)
        (self.source / 'tools/LocalExile.Export/NOTICE.md').write_text('changed source input')
        with self.assertRaisesRegex(package_module.PackageError, 'source changed'):
            self.package()
        self.assertFalse(self.target.exists())

    def test_a_package_without_a_release_tag_never_updates_itself(self):
        self.package()
        manifest = ET.parse(self.target / "manifest.xml").getroot()
        self.assertIsNone(manifest.find("Update"))
        self.assertEqual("1.1.0", manifest.find("Version").get("release"), "shown as the local copy's version")
        self.assertIsNone(manifest.find("Version").get("tag"))
        self.assertEqual([], manifest.findall("File"))

    def test_a_missing_or_malformed_version_stops_packaging(self):
        for text, message in ((None, "VERSION file is missing"), ("1.1", "semantic version"), ("v1.1.0", "semantic version"),
                              ("01.1.0", "semantic version"), ("1.1.0+build", "semantic version")):
            if text is None:
                (self.source / "VERSION").unlink()
            else:
                (self.source / "VERSION").write_text(text)
            with self.assertRaisesRegex(package_module.PackageError, message):
                self.package()
        self.assertFalse(self.target.exists())


TAG = "evrybuild-v1.1.0"


class ReleasePackageTests(PackageTests):
    """Release packages: built from a clean commit, with an update manifest of what GitHub serves for it."""
    def setUp(self):
        super().setUp()
        (self.source / "CHANGELOG.md").write_text("# Changelog\n\n## 1.1.0 - 2026-11-10\n\n- Updates in place.\n\n## 1.0.0 - 2026-11-04\n\n- Old.\n")
        (self.source / ".gitignore").write_text("runtime/LocalExile/\nsrc/Builds/\nsrc/Update/\nsrc/*.xml\nsrc/*.json\nsrc/*.ini\nsrc/*.run\nsrc/*.cfg\n")
        # Committed with LF; the working copy then gets CRLF, as a Windows checkout does.
        (self.source / "src/Launch.lua").write_bytes(b"line one\nline two\n")
        self.git("init", "-q")
        self.git("add", "-A")
        self.git("commit", "-q", "-m", "fixture")
        self.commit = self.git("rev-parse", "HEAD").strip()
        (self.source / "src/Launch.lua").write_bytes(b"line one\r\nline two\r\n")
        self.git("update-index", "--assume-unchanged", "src/Launch.lua")

    def git(self, *args):
        return package_module.subprocess.run(["git", "-C", str(self.source), "-c", "user.name=t", "-c", "user.email=t@t",
                                              "-c", "core.autocrlf=false", *args],
                                             capture_output=True, text=True, check=True).stdout

    def release_package(self, base=None, assets=None):
        return package_module.package(self.source, self.target, package_module.parse_release(TAG, base), assets)

    def test_release_manifest_lists_every_file_by_its_committed_bytes(self):
        assets = self.folder / "assets"
        result = self.release_package(assets=assets)
        self.assertEqual(("1.1.0", TAG, self.commit), (result["version"], result["tag"], result["sourceRevision"]))
        self.assertEqual(b"line one\nline two\n", (self.target / "Launch.lua").read_bytes(), "the committed bytes, not the working copy")
        manifest = ET.parse(self.target / "manifest.xml").getroot()
        version = manifest.find("Version")
        self.assertEqual(("1.1.0", TAG, self.commit, "evrybuild", "win32"),
                         tuple(version.get(k) for k in ("release", "tag", "commit", "branch", "platform")))
        self.assertEqual("https://github.com/LocalExile/evryBuild/releases/latest/download/evryBuild-update.xml",
                         manifest.find("Update").get("url"))
        sources = {s.get("part"): s.get("url") for s in manifest.findall("Source")}
        self.assertEqual({"repo": f"https://raw.githubusercontent.com/LocalExile/evryBuild/{self.commit}/",
                          "asset": f"https://github.com/LocalExile/evryBuild/releases/download/{TAG}/"}, sources)
        self.assertEqual("## 1.1.0 - 2026-11-10\n\n- Updates in place.", manifest.find("Notes").text)
        files = {f.get("name"): f for f in manifest.findall("File")}
        packaged = {p.relative_to(self.target).as_posix() for p in self.target.rglob("*") if p.is_file()}
        self.assertEqual(packaged - {"manifest.xml", "evryBuild.cmd"}, set(files))
        for name, entry in files.items():
            content = (self.target / name).read_bytes()
            self.assertEqual((hashlib.sha256(content).hexdigest(), str(len(content))), (entry.get("sha256"), entry.get("size")), name)
        self.assertEqual(("repo", "src/Launch.lua"), (files["Launch.lua"].get("part"), files["Launch.lua"].get("source")))
        self.assertEqual(("repo", "runtime/" + package_module.HOST), (files["evryBuild.exe"].get("part"), files["evryBuild.exe"].get("source")))
        self.assertEqual(("repo", "README.md"), (files["README.md"].get("part"), files["README.md"].get("source")))
        self.assertEqual(("asset", "evryBuild.Export.exe"), (files["LocalExile/evryBuild.Export.exe"].get("part"),
                                                             files["LocalExile/evryBuild.Export.exe"].get("source")))
        self.assertEqual("asset", files["evryBuild-package.json"].get("part"))
        self.assertEqual({"evryBuild.exe", "lua51.dll", "SimpleGraphic.dll", "lcurl.dll", "libcurl.dll", "zlib1.dll", "msvcr100.dll"},
                         {n for n, f in files.items() if f.get("native") == "true"})
        record = json.loads((self.target / "evryBuild-package.json").read_text())
        self.assertEqual(("1.1.0", TAG, self.commit), (record["version"], record["tag"], record["sourceRevision"]))
        self.assertEqual({"evryBuild-update.xml", "evryBuild.Export.exe", "evryBuild-package.json"}, {p.name for p in assets.iterdir()})
        self.assertEqual((self.target / "manifest.xml").read_bytes(), (assets / "evryBuild-update.xml").read_bytes())

    def test_a_test_server_can_stand_in_for_github(self):
        self.release_package(base="http://127.0.0.1:8123/")
        manifest = ET.parse(self.target / "manifest.xml").getroot()
        self.assertEqual("http://127.0.0.1:8123/releases/latest/download/evryBuild-update.xml", manifest.find("Update").get("url"))
        self.assertEqual({"repo": f"http://127.0.0.1:8123/raw/{self.commit}/", "asset": f"http://127.0.0.1:8123/releases/download/{TAG}/"},
                         {s.get("part"): s.get("url") for s in manifest.findall("Source")})

    def test_uncommitted_or_untracked_application_files_are_refused(self):
        (self.source / "help.txt").write_text("changed but not committed")
        with self.assertRaisesRegex(package_module.PackageError, "clean commit"):
            self.release_package()
        self.git("checkout", "--", "help.txt")
        (self.source / "src/Modules/Untracked.lua").write_text("not committed")
        self.entries.append(("program", "Modules/Untracked.lua"))
        self.write_manifest()
        self.git("add", "manifest.xml")
        self.git("commit", "-q", "-m", "manifest lists an untracked file")
        with self.assertRaisesRegex(package_module.PackageError, "not committed"):
            self.release_package()
        self.assertFalse(self.target.exists())

    def test_release_tags_and_options_are_checked(self):
        for tag in ("1.1.0", "v1.1.0", "evrybuild-1.1.0", "evrybuild-v1.1", "evrybuild-v01.1.0", "Evrybuild-v1.1.0",
                    "evrybuild-v1.1.0-", "evrybuild-v1.1.0+build", "evrybuild-localexile-external-2026.11.10"):
            with self.assertRaisesRegex(package_module.PackageError, "Release tags"):
                package_module.parse_release(tag, None)
        self.assertEqual("1.3.0-rc.1", package_module.parse_release("evrybuild-v1.3.0-rc.1", None).label)
        with self.assertRaisesRegex(package_module.PackageError, "belong to upstream PoB"):
            package_module.parse_release("v1.1.0", None)
        with self.assertRaisesRegex(package_module.PackageError, "needs --release-tag"):
            package_module.parse_release(None, "http://127.0.0.1:1/")
        with self.assertRaisesRegex(package_module.PackageError, "ending in /"):
            package_module.parse_release(TAG, "http://127.0.0.1:1")
        with self.assertRaisesRegex(package_module.PackageError, "--assets is for release packages"):
            package_module.package(self.source, self.target, None, self.folder / "assets")

    def test_tag_version_and_changelog_must_agree(self):
        with self.assertRaisesRegex(package_module.PackageError, "does not match VERSION 1.1.0.*evrybuild-v1.1.0"):
            package_module.package(self.source, self.target, package_module.parse_release("evrybuild-v1.2.0", None))
        changelog = self.source / "CHANGELOG.md"
        for text, message in (("# Changelog\n\n## 1.0.0 - 2026-11-04\n", "must be headed '## 1.1.0"),
                              ("# Changelog\n\n## 1.1.0-rc.1 - 2026-11-09\n", "must be headed '## 1.1.0"),
                              ("# Changelog\n\n## 1.1.0 - unreleased\n", "still calls 1.1.0 unreleased")):
            changelog.write_text(text)
            self.git("commit", "-q", "-am", "changelog")
            with self.assertRaisesRegex(package_module.PackageError, message):
                self.release_package()
        self.assertFalse(self.target.exists())

    def test_an_uncommitted_version_is_refused(self):
        (self.source / "VERSION").write_text("1.2.0\n")
        with self.assertRaisesRegex(package_module.PackageError, "clean commit"):
            package_module.package(self.source, self.target, package_module.parse_release("evrybuild-v1.2.0", None))


def wine_archive(path, members, root=appimage_module.WINE_ROOT):
    """A small stand-in for the Wine build: {name: bytes, or ('link', target)}."""
    with tarfile.open(path, "w:xz") as tar:
        for name, content in members.items():
            info = tarfile.TarInfo(f"{root}/{name}")
            if isinstance(content, tuple):
                info.type, info.linkname = tarfile.SYMTYPE, content[1]
                tar.addfile(info)
            else:
                info.size, info.mode = len(content), 0o755 if name.startswith("bin/") else 0o644
                tar.addfile(info, io.BytesIO(content))


WINE_FILES = {"bin/wine": b"loader", "bin/wineserver": b"server", "bin/winegcc": b"compiler", "bin/winepath": b"paths",
              "lib/wine/x86_64-windows/kernel32.dll": b"pe", "lib/wine/x86_64-windows/libkernel32.a": b"import lib",
              "lib/wine/x86_64-unix/ntdll.so": b"unix", "lib/wine/i386-windows/kernel32.dll": b"32-bit pe",
              "include/wine/windows/windows.h": b"header", "share/man/man1/wine.1": b"manual",
              "share/applications/wine.desktop": b"desktop entry", "share/wine/wine.inf": b"inf",
              "share/wine/fonts/tahoma.ttf": b"font", "lib/wine/x86_64-unix/libwine.so": ("link", "ntdll.so")}


class AppImageTests(unittest.TestCase):
    """The AppImage's layout, launcher and pinned downloads. appimagetool and the network are not used."""
    # The same synthetic source checkout as the portable package tests.
    setUp, tearDown, write_manifest = PackageTests.setUp, PackageTests.tearDown, PackageTests.write_manifest

    def test_pins_are_exact_https_files_with_sha256(self):
        for pin in (appimage_module.WINE, appimage_module.APPIMAGETOOL, appimage_module.RUNTIME):
            self.assertTrue(pin.url.startswith("https://github.com/") and "/releases/download/" in pin.url, pin.url)
            self.assertNotIn("continuous", pin.url)
            self.assertRegex(pin.sha256, r"^[0-9a-f]{64}$")
        self.assertEqual(appimage_module.WINE.name, appimage_module.WINE_ROOT + ".tar.xz")
        notice = (appimage_module.FILES / "notices/NOTICE-Wine.md").read_text(encoding="utf-8")
        self.assertIn(appimage_module.WINE.name, notice)
        version = re.match(r"wine-([0-9.]+)-", appimage_module.WINE.name).group(1)
        self.assertIn(f"https://dl.winehq.org/wine/source/{version}/wine-{version}.tar.xz", notice)
        self.assertIn(f"tree/wine-{version}", notice)
        self.assertIn("Lesser General Public License", (appimage_module.FILES / "notices/WINE-COPYING.LIB.txt").read_text())

    def test_launcher_uses_the_bundled_wine_and_a_prefix_outside_the_image(self):
        launcher = (appimage_module.FILES / "AppRun").read_text(encoding="utf-8")
        self.assertTrue(launcher.startswith("#!/bin/sh\n"))
        self.assertNotIn("\r", launcher)
        for folder in (appimage_module.APP_DIR, appimage_module.WINE_DIR):
            self.assertIn(f'"$HERE/{folder}"', launcher)
        self.assertIn('WINEPREFIX="${EVRYBUILD_WINEPREFIX:-$DATA_HOME/appimage-prefix}"', launcher)
        self.assertIn("EVRYBUILD_APPIMAGE=", launcher)
        self.assertIn('exec "$WINELOADER" evryBuild.exe', launcher)
        desktop = (appimage_module.FILES / "evryBuild.desktop").read_text(encoding="utf-8")
        self.assertIn("Icon=evryBuild\n", desktop)
        self.assertTrue((appimage_module.FILES / "evryBuild.png").read_bytes().startswith(b"\x89PNG"))

    def test_appdir_holds_the_portable_application_wine_launcher_and_notices(self):
        archive = self.folder / "wine.tar.xz"
        wine_archive(archive, WINE_FILES)
        appdir = self.folder / "evryBuild.AppDir"
        with patch.object(package_module, "source_revision", return_value="source-commit"):
            result = appimage_module.build_appdir(self.source, appdir, archive, None)
        self.assertTrue(result["ok"])
        app = appdir / appimage_module.APP_DIR
        self.assertEqual((app / "evryBuild.exe").read_bytes(), (self.source / "runtime" / package_module.HOST).read_bytes())
        self.assertTrue((app / "LocalExile/evryBuild.Export.exe").is_file())
        self.assertFalse((app / "Settings.xml").exists())
        self.assertTrue(os.access(appdir / "AppRun", os.X_OK))
        for name in ("evryBuild.desktop", "evryBuild.png", ".DirIcon"):
            self.assertTrue((appdir / name).is_file(), name)
        wine = appdir / appimage_module.WINE_DIR
        kept = {p.relative_to(wine).as_posix() for p in wine.rglob("*") if p.is_file() or p.is_symlink()}
        self.assertEqual({"bin/wine", "bin/wineserver", "bin/winepath", "lib/wine/x86_64-windows/kernel32.dll",
                          "lib/wine/x86_64-unix/ntdll.so", "lib/wine/x86_64-unix/libwine.so", "share/wine/wine.inf",
                          "share/wine/fonts/tahoma.ttf"}, kept)
        self.assertTrue(os.access(wine / "bin/wine", os.X_OK))
        self.assertEqual("ntdll.so", os.readlink(wine / "lib/wine/x86_64-unix/libwine.so"))
        notices = appdir / appimage_module.DOC_DIR / "wine"
        self.assertEqual({"NOTICE-Wine.md", "WINE-LICENSE.txt", "WINE-COPYING.LIB.txt"}, {p.name for p in notices.iterdir()})

    def test_wine_archives_that_leave_their_folder_or_lack_wine_are_refused(self):
        for members, root, message in (
                ({**WINE_FILES, "bin/../../escape": b"x"}, appimage_module.WINE_ROOT, "Unexpected path"),
                ({**WINE_FILES, "lib/outside": ("link", "../../../etc/passwd")}, appimage_module.WINE_ROOT, "leaves Wine"),
                ({**WINE_FILES, "lib/absolute": ("link", "/etc/passwd")}, appimage_module.WINE_ROOT, "leaves Wine"),
                (WINE_FILES, "other-root", "Unexpected path"),
                ({k: v for k, v in WINE_FILES.items() if k != "bin/wineserver"}, appimage_module.WINE_ROOT, "bin/wineserver")):
            with self.subTest(message=message, root=root):
                archive = self.folder / "bad.tar.xz"
                wine_archive(archive, members, root)
                destination = self.folder / "bad-wine"
                with self.assertRaisesRegex(package_module.PackageError, message):
                    appimage_module.extract_wine(archive, destination)
                archive.unlink()
                shutil.rmtree(destination, ignore_errors=True)

    def test_a_download_that_differs_from_its_pin_is_never_kept(self):
        cache = self.folder / "cache"
        pin = appimage_module.Pin("https://example.invalid/tool", hashlib.sha256(b"expected").hexdigest())

        def answer(content):
            return patch.object(appimage_module.urllib.request, "urlopen", return_value=io.BytesIO(content))

        with answer(b"tampered"), self.assertRaisesRegex(package_module.PackageError, "not the pinned"):
            appimage_module.fetch(pin, cache)
        self.assertEqual([], list(cache.iterdir()))
        with answer(b"expected"):
            self.assertEqual(b"expected", appimage_module.fetch(pin, cache).read_bytes())
        with patch.object(appimage_module.urllib.request, "urlopen", side_effect=AssertionError("cached file is reused")):
            appimage_module.fetch(pin, cache)

    def test_an_existing_or_misnamed_output_is_refused_before_downloading(self):
        existing = self.folder / "evryBuild-x86_64.AppImage"
        existing.write_bytes(b"earlier build")
        with patch.object(appimage_module, "fetch", side_effect=AssertionError("no download")):
            for output, message in ((existing, "already exists"), (self.folder / "evryBuild.zip", r"\.AppImage"),
                                    (self.folder / "missing/evryBuild-x86_64.AppImage", "parent folder"),
                                    (self.source / "src/evryBuild-x86_64.AppImage", "application or runtime")):
                with self.subTest(output=output), self.assertRaisesRegex(package_module.PackageError, message):
                    appimage_module.build(self.source, output, self.folder / "cache")
        self.assertEqual(b"earlier build", existing.read_bytes())


if __name__ == "__main__":
    unittest.main()
