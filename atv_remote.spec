# -*- mode: python ; coding: utf-8 -*-

block_cipher = None

# 需要让 PyInstaller 知道的隐藏 pyatv 依赖
hiddenimports = [
    'pyatv',
    'uvicorn',
    'fastapi',
    'pydantic',
    'pystray',
    'PIL',
    'webbrowser',
    # pyatv dependencies
    'asyncio',
    'aiohttp',
    'cryptography',
    'zeroconf',
    'ifaddr',
    'bitarray',
    'google.protobuf',
]

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('static', 'static')],  # 打包 static 文件夹
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='AppleTVRemote',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True, # 暂时设为 True 以便调试启动错误
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='AppleTVRemoteApp',
)
