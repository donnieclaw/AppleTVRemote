@echo off
echo Initializing Apple TV Remote Build Project...

cd /d "%~dp0"

echo [1/3] Creating virtual environment and installing dependencies...
python -m venv venv
call venv\Scripts\activate
pip install -r requirements.txt
pip install pyinstaller

echo [2/3] Building with PyInstaller...
pyinstaller --clean --noconfirm atv_remote.spec

echo [3/3] Done!
echo You can run the setup.iss script with Inno Setup to create an installer.
echo Standalone executable is located at: dist\AppleTVRemoteApp\AppleTVRemote.exe
pause
