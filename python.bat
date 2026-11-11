@echo off
chcp 65001 > nul
title Automatizador de Acionamentos - Suporte NOC

:: Garante que o terminal abra exatamente na pasta onde este .bat está salvo
cd /d "%~dp0"

:: Verifica se o script Python existe na pasta
if not exist "automacao_3.py" (
    echo [!] ERRO: O arquivo "automacao_3.py" nao foi encontrado nesta pasta!
    echo Certifique-se de que o .bat e o .py estao no mesmo diretorio.
    pause
    exit /b 1
)

:: Define o caminho dinamico do Python no perfil do usuario atual
set "PYTHON_PATH=%LOCALAPPDATA%\Python\pythoncore-3.15-64\python.exe"

if exist "%PYTHON_PATH%" (
    "%PYTHON_PATH%" automacao_3.py
) else (
    python automacao_3.py
)

:: Verifica se o script fechou com erro ou de forma normal
if %errorlevel% neq 0 (
    echo.
    echo ========================================================
    echo [!] Ocorreu um erro durante a execucao do script acima.
    echo ========================================================
    pause
) else (
    echo.
    echo [OK] Programa encerrado com sucesso.
    timeout /t 3 > nul
)
