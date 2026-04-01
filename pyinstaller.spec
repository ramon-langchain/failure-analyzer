# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_all


packages = [
    "deepagents",
    "langchain",
    "langchain_core",
    "langchain_openai",
    "langgraph",
    "openai",
    "tiktoken",
    "dotenv",
]

datas = []
binaries = []
hiddenimports = []

for package in packages:
    collected_datas, collected_binaries, collected_hiddenimports = collect_all(package)
    datas += collected_datas
    binaries += collected_binaries
    hiddenimports += collected_hiddenimports


a = Analysis(
    ["src/test_analyzer/__main__.py"],
    pathex=["src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="test-analyzer",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
)
