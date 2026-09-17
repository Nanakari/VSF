# -*- mode: python ; coding: utf-8 -*-


from pathlib import Path


PROJECT_DIR = Path.cwd()


a = Analysis(
    [str(PROJECT_DIR / 'indexer_app.py')],
    pathex=[str(PROJECT_DIR)],
    binaries=[],
    datas=[
        (str(PROJECT_DIR / 'templates'), 'templates'),
        (str(PROJECT_DIR / 'static'), 'static'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'IPython',
        'PIL',
        'PyQt5',
        'astroid',
        'cloudpickle',
        'docutils',
        'gevent',
        'jedi',
        'jsonschema',
        'jupyter_client',
        'jupyter_core',
        'lib2to3',
        'matplotlib',
        'nbformat',
        'numpy',
        'parso',
        'psutil',
        'pygments',
        'pytest',
        'scipy',
        'sphinx',
        'tkinter',
        'traitlets',
        'zmq',
    ],
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
    name='VTuberSongFinderSetup',
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
