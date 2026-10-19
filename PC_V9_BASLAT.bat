@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Bitget BTC ETH - Sanal Islem Paneli V9.3

echo ============================================================
echo   BITGET BTC / ETH SANAL BOT V9.3 - GERCEK EMIR YOK
echo ============================================================
echo.
echo Bu program kendi bilgisayarinda calisir.
echo Bilgisayar kapali veya uyku modundayken takip durur.
echo.

set "PY_EXE="
set "PY_ARGS="
if exist "%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe" set "PY_EXE=%LOCALAPPDATA%\Python\pythoncore-3.14-64\python.exe"
if not defined PY_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
if not defined PY_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if not defined PY_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if not defined PY_EXE if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set "PY_EXE=%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if not defined PY_EXE (
    where py >nul 2>&1
    if not errorlevel 1 (
        set "PY_EXE=py"
        set "PY_ARGS=-3"
    )
)
if not defined PY_EXE (
    where python >nul 2>&1
    if not errorlevel 1 set "PY_EXE=python"
)
if not defined PY_EXE goto no_python

echo Python surumu kontrol ediliyor...
"%PY_EXE%" %PY_ARGS% -c "import sys; assert sys.version_info >= (3,9), sys.version; print(sys.version)"
if errorlevel 1 goto no_python

echo.
echo Bitget sanal paneli guncel GitHub deposundan indiriliyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $url='https://raw.githubusercontent.com/burkayylmaz05-dev/bitget-sanal-takip/main/pc_sanal_v9.py'; $tmp='pc_sanal_v9.py.downloading'; try {Invoke-WebRequest -Uri $url -OutFile $tmp -TimeoutSec 45 -UseBasicParsing; if ((Get-Item $tmp).Length -lt 12000) {throw 'Python dosyasi eksik indirildi'}; Move-Item $tmp 'pc_sanal_v9.py' -Force; } finally { if (Test-Path $tmp) {Remove-Item $tmp -Force} }"
if errorlevel 1 goto download_error

echo.
echo Sanal panelin Python kodu kontrol ediliyor...
"%PY_EXE%" %PY_ARGS% -m py_compile "pc_sanal_v9.py"
if errorlevel 1 goto compile_error

echo.
echo Panel aciliyor: http://127.0.0.1:8765
echo Bu pencere acik kaldigi surece BTC / ETH sanal test devam eder.
echo Stop-loss ve sonuclar varsayimsal; Bitget gercek emir YOK.
echo.
"%PY_EXE%" %PY_ARGS% -X utf8 "pc_sanal_v9.py"

echo.
echo Program kapandi. Sanal kayitlar silinmedi.
pause
exit /b 0

:no_python
echo.
echo HATA: Python 3.9 veya daha yeni surum bulunamadi.
echo Mevcut Python kurulumunu kontrol edin.
goto failed

:download_error
echo.
echo HATA: GitHub'dan dosya indirilemedi.
echo Internet baglantinizi kontrol edin; eski dosya silinmedi.
goto failed

:compile_error
echo.
echo HATA: Python kodu derlenemedi. Bot baslatilmadi.
goto failed

:failed
pause
exit /b 1
