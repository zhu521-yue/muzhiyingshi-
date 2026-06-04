# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['server.py'],
    pathex=[],
    binaries=[('D:/Anaconda/envs/bishe/Library/bin/libssl-3-x64.dll', '.'), ('D:/Anaconda/envs/bishe/Library/bin/libcrypto-3-x64.dll', '.')],
    datas=[('chart.min.js', '.'), ('木植控股.png', '.'), ('添润标识集合-06.png', '.'), ('喜文4.png', '.'), ('盈世标识.png', '.'), ('_html_template.py', '.'), ('core.py', '.'), ('db_manager.py', '.'), ('sync_task.py', '.'), ('config', 'config')],
    hiddenimports=['json', 'threading', 'concurrent.futures', 'socketserver', 'sqlite3'],
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
