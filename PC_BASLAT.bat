@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Bitget BTC ETH Canli Sinyal - 5m 15m 1H 4H

echo ======================================================
echo   BITGET PC CANLI BOT - BASLATICI (v4)
echo   BTC ve ETH: 5m / 15m / 1H / 4H
echo ======================================================
echo.

echo [1/4] Kurulu Python programi kontrol ediliyor...
set "PYTHON_EXE="
REM Bilgisayarda gorunen Python314 kurulum yolunu PATH kullanmadan bulur.
for %%V in (314 313 312 311 310 39) do (
  if not defined PYTHON_EXE (
    if exist "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" (
      "%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe" -c "import sys; assert sys.version_info >= (3,9)" >nul 2>&1
      if not errorlevel 1 set "PYTHON_EXE=%LOCALAPPDATA%\Programs\Python\Python%%V\python.exe"
    )
  )
)
if not defined PYTHON_EXE (
  if exist "%LOCALAPPDATA%\Python\bin\python.exe" (
    "%LOCALAPPDATA%\Python\bin\python.exe" -c "import sys; assert sys.version_info >= (3,9)" >nul 2>&1
    if not errorlevel 1 set "PYTHON_EXE=%LOCALAPPDATA%\Python\bin\python.exe"
  )
)
if not defined PYTHON_EXE (
  echo.
  echo HATA: Python dogrudan kurulum adresinden de acilamadi.
  echo Teshis icin su dosyayi kontrol edin:
  echo "%LOCALAPPDATA%\Programs\Python\Python314\python.exe"
  if exist "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" (
    "%LOCALAPPDATA%\Programs\Python\Python314\python.exe" --version
  ) else (
    echo Python314 dosyasi bu adreste bulunamadi.
  )
  goto :error
)
echo Python bulundu: "%PYTHON_EXE%"
"%PYTHON_EXE%" --version

echo.
echo [2/4] Bot dosyalari GitHub'dan indiriliyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $base='https://raw.githubusercontent.com/burkayylmaz05-dev/bitget-sanal-takip/main/'; $names=@('bitget_sinyal_takip.py','pc_zaman_dilimleri.py','pc_canli_bot.py'); foreach($name in $names){ $tmp=$name+'.downloading'; try { Write-Host ('Indiriliyor: '+$name); Invoke-WebRequest -Uri ($base+$name+'?v='+[DateTime]::UtcNow.Ticks) -OutFile $tmp -UseBasicParsing -TimeoutSec 45; if ((Get-Item -LiteralPath $tmp).Length -lt 200) { throw ('Bos veya eksik dosya: '+$name) }; Move-Item -LiteralPath $tmp -Destination $name -Force -ErrorAction Stop; Write-Host ('Tamam: '+$name) } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue } }"
if errorlevel 1 (
  echo.
  echo HATA: Guncelleme tamamlanamadi.
  echo Yukaridaki PowerShell hata mesajinin ekran goruntusunu gonderin.
  goto :error
)

echo.
echo [3/4] Python dosyalari kontrol ediliyor...
"%PYTHON_EXE%" -m py_compile bitget_sinyal_takip.py pc_zaman_dilimleri.py pc_canli_bot.py
if errorlevel 1 (
  echo HATA: Python dosyalarinda derleme hatasi.
  goto :error
)
"%PYTHON_EXE%" -c "import websocket; assert hasattr(websocket, 'WebSocketApp')" >nul 2>&1
if errorlevel 1 (
  echo websocket-client ucretsiz kutuphanesi kuruluyor...
  "%PYTHON_EXE%" -m pip --version >nul 2>&1
  if errorlevel 1 "%PYTHON_EXE%" -m ensurepip --upgrade
  "%PYTHON_EXE%" -m pip install --disable-pip-version-check "websocket-client>=1.8,<2"
  if errorlevel 1 (
    echo HATA: websocket-client kutuphanesi kurulamadi.
    goto :error
  )
)

echo.
echo [4/4] Bot baslatiliyor.
echo Bu pencere acik kaldigi surece takip devam eder.
echo.
"%PYTHON_EXE%" -X utf8 pc_canli_bot.py
if errorlevel 1 echo Bot hata ile durdu. Yukaridaki hata mesajini gonderin.
echo.
pause
exit /b 0

:error
echo.
echo Lutfen ekrandaki hata mesajini ChatGPT'ye gonderin.
pause
exit /b 1
