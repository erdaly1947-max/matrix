@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title FIRSAT-KONTROL PANELİ - Başlat

rem Uygulama, Python kaynak dosyalarindan calistirilir; uygulama EXE'si baslatilmaz.
set "PYTHON="
set "PYDIR="
set "CANDIDATE_DIR="

rem Once Python Launcher uzerinden kurulu surumleri dene.
for %%V in (3.14 3.13 3.12 3.11) do if not defined PYTHON (
    for /f "delims=" %%P in ('py -%%V -c "import sys; print(sys.executable)" 2^>nul') do call :TRY_PYTHON "%%P"
)

rem Python Launcher yoksa Windows kayit defterindeki kurulum yollarini ara.
if not defined PYTHON (
    for %%V in (3.14 3.13 3.12 3.11) do if not defined PYTHON (
        for /f "tokens=2,*" %%A in ('reg query "HKCU\Software\Python\PythonCore\%%V\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"') do (
            if exist "%%Bpython.exe" call :TRY_PYTHON "%%Bpython.exe"
            if not defined PYTHON if exist "%%B\python.exe" call :TRY_PYTHON "%%B\python.exe"
        )
    )
)
if not defined PYTHON (
    for %%V in (3.14 3.13 3.12 3.11) do if not defined PYTHON (
        for /f "tokens=2,*" %%A in ('reg query "HKLM\Software\Python\PythonCore\%%V\InstallPath" /ve 2^>nul ^| findstr /i "REG_SZ"') do (
            if exist "%%Bpython.exe" call :TRY_PYTHON "%%Bpython.exe"
            if not defined PYTHON if exist "%%B\python.exe" call :TRY_PYTHON "%%B\python.exe"
        )
    )
)

rem Python Install Manager komutlari PATH disinda kalmis olabilir.
if not defined PYTHON if exist "%LocalAppData%\Python\bin\python.exe" call :TRY_PYTHON "%LocalAppData%\Python\bin\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Python\bin\python3.14.exe" call :TRY_PYTHON "%LocalAppData%\Python\bin\python3.14.exe"
if not defined PYTHON if exist "%LocalAppData%\Python\bin\python3.exe" call :TRY_PYTHON "%LocalAppData%\Python\bin\python3.exe"

rem Standart kurulum konumlarini kontrol et.
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python314\python.exe" call :TRY_PYTHON "%LocalAppData%\Programs\Python\Python314\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python313\python.exe" call :TRY_PYTHON "%LocalAppData%\Programs\Python\Python313\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python312\python.exe" call :TRY_PYTHON "%LocalAppData%\Programs\Python\Python312\python.exe"
if not defined PYTHON if exist "%LocalAppData%\Programs\Python\Python311\python.exe" call :TRY_PYTHON "%LocalAppData%\Programs\Python\Python311\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python314\python.exe" call :TRY_PYTHON "%ProgramFiles%\Python314\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python313\python.exe" call :TRY_PYTHON "%ProgramFiles%\Python313\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python312\python.exe" call :TRY_PYTHON "%ProgramFiles%\Python312\python.exe"
if not defined PYTHON if exist "%ProgramFiles%\Python311\python.exe" call :TRY_PYTHON "%ProgramFiles%\Python311\python.exe"
if not defined PYTHON if exist "C:\Python314\python.exe" call :TRY_PYTHON "C:\Python314\python.exe"
if not defined PYTHON if exist "C:\Python313\python.exe" call :TRY_PYTHON "C:\Python313\python.exe"

rem Son olarak PATH uzerindeki python komutunu dene.
if not defined PYTHON (
    for /f "delims=" %%P in ('where python 2^>nul') do call :TRY_PYTHON "%%P"
)

if not defined PYTHON (
    echo Tkinter ve pythonw.exe bilesenleri bulunan uygun bir Python kurulumunu bulamadim.
    echo Python'un Tcl/Tk arayuz bileseniyle birlikte kuruldugunu kontrol edin.
    echo Bu pencereyi kapatmadan destek icin hata metnini paylasin.
    pause
    exit /b 1
)

"%PYTHON%" -c "import sys; print('Python', sys.version); print(sys.executable)"
if errorlevel 1 (
    echo Bulunan Python calistirilamadi. Hata yukarida gorunuyor.
    pause
    exit /b 1
)
echo.
"%PYTHON%" -c "import tkinter" >nul 2>nul
if errorlevel 1 (
    echo Python Tkinter bileseni bulunamadi.
    echo Tkinter pip ile requirements.txt dosyasindan kurulamaz; Python kurulumunda Tcl/Tk bileseni etkin olmalidir.
    pause
    exit /b 1
)
echo Gerekli paketler kontrol ediliyor...
"%PYTHON%" -c "import requests, websocket" >nul 2>nul
if errorlevel 1 (
    "%PYTHON%" -m pip --version >nul 2>nul
    if errorlevel 1 (
        echo Python pip modulu bulunamadi. Python kurulumunda pip etkin olmalidir.
        pause
        exit /b 1
    )
    "%PYTHON%" -m pip install --user -r "%~dp0requirements.txt"
    if errorlevel 1 (
        echo Paket kurulumu basarisiz oldu. Hata metni yukarida gorunuyor.
        pause
        exit /b 1
    )
    "%PYTHON%" -c "import requests, websocket" >nul 2>nul
    if errorlevel 1 (
        echo Paketler kurulduktan sonra Python bilesenleri hala yuklenemiyor.
        pause
        exit /b 1
    )
)

start "FIRSAT-KONTROL PANELİ" "%PYDIR%pythonw.exe" "%~dp0tek_motor_paneli.pyw"
exit /b 0

:TRY_PYTHON
if defined PYTHON exit /b 0
if not exist "%~1" exit /b 0
"%~1" -c "import tkinter" >nul 2>nul
if errorlevel 1 exit /b 0
for %%P in ("%~1") do set "CANDIDATE_DIR=%%~dpP"
if not exist "%CANDIDATE_DIR%pythonw.exe" exit /b 0
set "PYTHON=%~1"
set "PYDIR=%CANDIDATE_DIR%"
exit /b 0
