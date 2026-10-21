@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title Instalacao - Enviador de Curriculos
echo.
echo  Instalando o Enviador de Curriculos...
echo.

rem Procura um Python 3.10 ou mais novo, de 64 bits
set "PY="
set "TESTE=import sys,struct; sys.exit(0 if sys.version_info>=(3,10) and struct.calcsize('P')==8 else 1)"
for %%V in (3.13 3.12 3.11 3.10 3) do (
  if not defined PY (
    py -%%V -c "%TESTE%" >nul 2>&1 && set "PY=py -%%V"
  )
)
if not defined PY (
  python -c "%TESTE%" >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo  Nao encontrei o Python 3.10 ou mais novo, de 64 bits.
  echo  Vou instalar o Python 3.13 pelo winget. Aceite as permissoes que aparecerem.
  echo.
  winget install -e --id Python.Python.3.13 --accept-source-agreements --accept-package-agreements
  if errorlevel 1 (
    echo.
    echo  Nao consegui instalar automaticamente. Baixe em https://www.python.org/downloads/
    echo  e, na primeira tela do instalador, marque "Add python.exe to PATH".
    pause
    exit /b 1
  )
  echo.
  echo  Python instalado. Feche esta janela e de dois cliques em instalar.bat de novo.
  pause
  exit /b 0
)
echo  Usando o Python: %PY%

if not exist ".venv\Scripts\python.exe" (
  echo  Criando o ambiente isolado .venv ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo  Nao consegui criar o ambiente. Veja a mensagem acima.
    pause
    exit /b 1
  )
)

echo  Instalando as bibliotecas (pode levar um minuto)...
".venv\Scripts\python.exe" -m pip install --upgrade pip --quiet
".venv\Scripts\python.exe" -m pip install -r requirements.txt --quiet
if errorlevel 1 (
  echo.
  echo  A instalacao das bibliotecas falhou. Veja a mensagem acima.
  pause
  exit /b 1
)

echo.
if not exist "config.yaml" (
  echo  Agora vamos configurar. Responda as perguntas a seguir.
  ".venv\Scripts\python.exe" -m enviador configurar
) else (
  echo  Ja existe um config.yaml. Para refazer a configuracao, use a aba Configuracoes do painel.
)

echo.
echo  Pronto! Para usar, de dois cliques em abrir_painel.bat
echo.
pause
