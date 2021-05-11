rmdir /q /s import-mailbox-to-gmail
rmdir /q /s import-mailbox-to-gmail-64
rmdir /q /s build
rmdir /q /s dist
del /q /f import-mailbox-to-gmail-%1-windows.zip
del /q /f import-mailbox-to-gmail-%1-windows-x64.zip

c:\python27-32\scripts\pyinstaller -F --distpath=import-mailbox-to-gmail import-mailbox-to-gmail.spec
xcopy LICENSE import-mailbox-to-gmail\
del import-mailbox-to-gmail\w9xpopen.exe
"%ProgramFiles(x86)%\7-Zip\7z.exe" a -tzip import-mailbox-to-gmail-%1-windows.zip import-mailbox-to-gmail\ -xr!.svn

c:\python27\scripts\pyinstaller -F --distpath=import-mailbox-to-gmail-64 import-mailbox-to-gmail.spec
xcopy LICENSE import-mailbox-to-gmail-64\
xcopy whatsnew.txt import-mailbox-to-gmail-64\
"%ProgramFiles(x86)%\7-Zip\7z.exe" a -tzip import-mailbox-to-gmail-%1-windows-x64.zip import-mailbox-to-gmail-64\ -xr!.svn
