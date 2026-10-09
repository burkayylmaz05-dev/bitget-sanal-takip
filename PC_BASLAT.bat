@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
title Bitget BTC ETH Canli Sinyal Botu
where py >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
) else (
    set "PY=python"
)
%PY% --version >nul 2>&1
if errorlevel 1 (
    echo Python 3 bulunamadi. Once https://www.python.org/downloads/windows/ adresinden kurun.
    pause
    exit /b 1
)
echo Bitget botu kontrol ediliyor...
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $base='https://raw.githubusercontent.com/burkayylmaz05-dev/bitget-sanal-takip/main/'; Invoke-WebRequest ($base+'pc_canli_bot.py') -OutFile 'pc_canli_bot.py'; Invoke-WebRequest ($base+'bitget_sinyal_takip.py') -OutFile 'bitget_sinyal_takip.py'"
if errorlevel 1 (
    if not exist pc_canli_bot.py goto :fail
    if not exist bitget_sinyal_takip.py goto :fail
    echo Guncelleme alinamadi, mevcut dosyalarla devam ediliyor.
)
%PY% -c "import websocket; assert hasattr(websocket, 'WebSocketApp')" >nul 2>&1
if errorlevel 1 (
    echo Ucretsiz websocket-client kutuphanesi kuruluyor...
    %PY% -m pip install --disable-pip-version-check "websocket-client>=1.8,<2"
    if errorlevel 1 goto :fail
)
%PY% -X utf8 pc_canli_bot.py
pause
exit /b 0
:fail
echo Kurulum veya indirme basarisiz. Internet baglantisini kontrol edin.
pause
exit /b 1
