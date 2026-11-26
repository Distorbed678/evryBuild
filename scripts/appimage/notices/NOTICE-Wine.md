# Wine in the evryBuild AppImage

The Linux AppImage includes Wine 11.0, which runs the Windows planner and exporter. Wine is not part of evryBuild
and is not modified by it.

- Build: `wine-11.0-amd64-wow64.tar.xz` from Kron4ek's Wine-Builds, an unpatched ("vanilla") build of the Wine 11.0
  release: https://github.com/Kron4ek/Wine-Builds/releases/tag/11.0
- Source code of this exact Wine version: https://dl.winehq.org/wine/source/11.0/wine-11.0.tar.xz
  (also https://gitlab.winehq.org/wine/wine/-/tree/wine-11.0). The scripts that produced the build:
  https://github.com/Kron4ek/Wine-Builds
- Licence: GNU Lesser General Public License, version 2.1 or later. See `WINE-LICENSE.txt` and
  `WINE-COPYING.LIB.txt` beside this file. Copyright (c) 1993-2026 the Wine project authors; the full list is in
  the AUTHORS file of the source above.

The AppImage leaves out Wine's development files (headers, import libraries, compilers and manual pages), its
32-bit Windows libraries and its desktop entry. Nothing else in the Wine build is changed. You can replace the bundled
Wine with your own build of the source above by extracting the AppImage (`--appimage-extract`) and replacing
`squashfs-root/usr/lib/evryBuild/wine`.
