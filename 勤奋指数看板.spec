# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[('D:/Anaconda/envs/bishe/Library/bin/libssl-3-x64.dll', '.'), ('D:/Anaconda/envs/bishe/Library/bin/libcrypto-3-x64.dll', '.')],
    datas=[('59.jpg', '.'), ('chart.min.js', '.'), ('0db1696c72f14523ae22e96839216771.png', '.'), ('f49f00397e974bd3bb66f2099c0b7e3e.png', '.'), ('木植控股.png', '.'), ('添润标识集合-06.png', '.'), ('喜文4.png', '.'), ('盈世标识.png', '.'), ('_html_template.py', '.'), ('core.py', '.'), ('config', 'config')],
    hiddenimports=['json', 'threading', 'concurrent.futures', 'socketserver'],
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
    name='勤奋指数看板',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
