# -*- mode: python ; coding: utf-8 -*-
"""勤奋指数看板 - PyInstaller 打包配置

打包策略：
- 入口: launcher.py（GUI弹窗，无CMD窗口）
- 内嵌完整 HTTP 服务 + 所有公司看板
- 静态资源作为 data 文件打包进 exe
- config/ 和 cache/ 目录外置（用户可编辑配置、缓存持久化）
"""

import os

block_cipher = None

# 静态资源文件列表
datas = [
    ('59.jpg', '.'),
    ('chart.min.js', '.'),
    ('喜文4.png', '.'),
    ('木植控股.png', '.'),
    ('盈世标识.png', '.'),
    ('添润标识集合-06.png', '.'),
    ('_html_template.py', '.'),
    ('core.py', '.'),
    ('server.py', '.'),
]

# config 和 cache 目录外置（复制到 dist 目录旁）
# 打包时作为 data，运行时可编辑

a = Analysis(
    ['launcher.py'],
    pathex=[],
    binaries=[],
    datas=datas,
    hiddenimports=[
        'tkinter',
        'tkinter.ttk',
        'http.server',
        'urllib.request',
        'urllib.error',
        'urllib.parse',
        'json',
        'os',
        'sys',
        'threading',
        'time',
        'webbrowser',
        'socket',
        'datetime',
        'calendar',
        're',
        'traceback',
        'core',
        '_html_template',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'IPython',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='勤奋指数看板',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,           # 无CMD黑窗口
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
