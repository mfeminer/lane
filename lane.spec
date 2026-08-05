# PyInstaller spec for lane: one file, macOS arm64 first.
#
# Kept as a spec rather than a pile of command-line flags so the reasoning can live
# next to the settings. `make build` runs this.

a = Analysis(
    ["src/lane/__main__.py"],
    pathex=["src"],
    hiddenimports=[
        # tomli_w is imported lazily enough that PyInstaller's analysis can miss it.
        "tomli_w",
    ],
    excludes=[
        # Nothing in lane draws plots or serves web pages; keep the binary small.
        "tkinter",
        "unittest",
        "pydoc_data",
        "test",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="lane",
    onefile=True,
    console=True,
    strip=False,
    upx=False,
)
