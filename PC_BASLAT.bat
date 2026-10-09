@echo off
setlocal EnableExtensions
chcp 65001 >nul
cd /d "%~dp0"
title Bitget BTC ETH Canli Sinyal - 5m 15m 1H 4H

echo ======================================================
echo   BITGET PC CANLI BOT - YENI BASLATICI (v2)
echo   BTC ve ETH: 5m / 15m / 1H / 4H
echo ======================================================
echo.

echo [1/4] Python kontrol ediliyor...
set "PY=python"
where py >nul 2>&1
if not errorlevel 1 set "PY=py -3"
%PY% -c "import sys; assert sys.version_info >= (3,9)" >nul 2>&1
if errorlevel 1 (
  echo HATA: Python 3.9 veya daha yeni bir surum gerekli.
  echo https://www.python.org/downloads/windows/
  goto :error
)

echo [2/4] Guncel bot dosyalari GitHub'dan indiriliyor...
powershell.exe -NoProfile -ExecutionPolicy Bypass -Command "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; $base='https://raw.githubusercontent.com/burkayylmaz05-dev/bitget-sanal-takip/main/'; $names=@('bitget_sinyal_takip.py','pc_zaman_dilimleri.py','pc_canli_bot.py'); foreach($name in $names){ $tmp=$name+'.downloading'; try { Write-Host ('Indiriliyor: '+$name); Invoke-WebRequest -Uri ($base+$name+'?v='+[DateTime]::UtcNow.Ticks) -OutFile $tmp -UseBasicParsing -TimeoutSec 45; if ((Get-Item -LiteralPath $tmp).Length -lt 200) { throw ('Bos veya eksik dosya: '+$name) }; Move-Item -LiteralPath $tmp -Destination $name -Force -ErrorAction Stop; Write-Host ('Tamam: '+$name) } finally { Remove-Item -LiteralPath $tmp -Force -ErrorAction SilentlyContinue } }"
if errorlevel 1 (
  echo.
  echo HATA: Guncelleme tamamlanamadi. Yukaridaki PowerShell hatasina bakin.
  echo Internet baglantisini kontrol edin. Eski surum baslatilmadi.
  goto :error
)

echo [3/4] Python dosyalari kontrol ediliyor...
%PY% -m py_compile bitget_sinyal_takip.py pc_zaman_dilimleri.py pc_canli_bot.py
if errorlevel 1 (
  echo HATA: Python dosyalarinda derleme sorunu var.
  goto :error
)
%PY% -c "import websocket; assert hasattr(websocket, 'WebSocketApp')" >nul 2>&1
if errorlevel 1 (
  echo Ucretsiz websocket-client kutuphanesi kuruluyor...
  %PY% -m pip install --disable-pip-version-check "websocket-client>=1.8,<2"
  if errorlevel 1 (
    echo HATA: websocket-client kurulamadi.
    goto :error
  )
)

echo [4/4] Bot baslatiliyor. Bu pencere acik kalmali.
echo.
%PY% -X utf8 pc_canli_bot.py
if errorlevel 1 echo Bot hata ile durdu, mesajlari kontrol edin.
echo.
pause
exit /b 0

:error
echo.
echo Ekran goruntusunu ChatGPT'ye gonderirsen sorunu belirleyebilirim.
pause
exit /b 1
