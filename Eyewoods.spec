# -*- mode: python ; coding: utf-8 -*-

import platform

with open("build/version.txt", "r") as f:
    version = f.read()

a = Analysis(
    ["eyewoods.py"],
    pathex=[],
    binaries=[],
    datas=[("build/version.txt", ".")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

if platform.system() == "Darwin":
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="Eyewoods",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="Eyewoods",
    )
    app = BUNDLE(
        coll,
        name="Eyewoods.app",
        icon="icons/Eyewoods.icns",
        bundle_identifier=None,
        version=version,
        info_plist={
            "CFBundleDocumentTypes": [
                {
                    "CFBundleTypeName": "Eyewoods Config File",
                    "CFBundleTypeRole": "Editor",
                    "LSHandlerRank": "Owner",
                    "CFBundleTypeExtensions": ["eyewoods"],
                }
            ],
        },
    )

elif platform.system() == "Windows":
    exe = EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
        name="Eyewoods",
        icon="icons\\Eyewoods.ico",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )
