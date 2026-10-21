@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Enviador de Curriculos - painel
if not exist ".venv\Scripts\python.exe" (
  echo  O programa ainda nao foi instalado. De dois cliques em instalar.bat primeiro.
  pause
  exit /b 1
)
if not exist "config.yaml" (
  ".venv\Scripts\python.exe" -m enviador configurar
)
echo  Abrindo o painel no navegador. Deixe esta janela aberta enquanto usa.
echo  Para fechar, feche esta janela.
echo.
".venv\Scripts\python.exe" -m enviador painel
if errorlevel 1 pause
