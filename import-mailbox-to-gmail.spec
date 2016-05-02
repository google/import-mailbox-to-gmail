# -*- mode: python -*-
a = Analysis(['import-mailbox-to-gmail.py'],
             hiddenimports=[],
             hookspath=None,
             runtime_hooks=None)
for d in a.datas:
    if 'pyconfig' in d[0]: 
        a.datas.remove(d)
        break
a.datas += [('httplib2/cacerts.txt', 'c:\python27\lib\site-packages\httplib2\cacerts.txt', 'DATA')]
pyz = PYZ(a.pure)
exe = EXE(pyz,
          a.scripts,
          a.binaries,
          a.zipfiles,
          a.datas,
          name='import-mailbox-to-gmail.exe',
          debug=False,
          strip=None,
          upx=True,
          console=True )