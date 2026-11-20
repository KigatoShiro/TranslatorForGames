@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
where py >nul 2>nul && (set "PY=py -3") || (set "PY=python")
%PY% --version >nul 2>nul || (
  echo Не найден Python 3. Установите его с https://www.python.org/downloads/ ^(галочка "Add python.exe to PATH"^).
  pause & exit /b 1
)

:menu
cls
echo ================================================
echo   The Crew Motorfest - Settings Tweaker
echo   Закройте игру перед изменением настроек!
echo ================================================
echo  1. Показать все настройки (scan)
echo  2. Чистая картинка: выкл. blur / аберрацию / зерно / виньетку / DOF
echo  3. Снять лимит FPS и выключить V-Sync
echo  4. Максимальный FOV
echo  5. Всё сразу (2 + 3 + 4)
echo  6. Запретить игре сбрасывать настройки (lock)
echo  7. Разрешить запись настроек (unlock)
echo  8. Откатить последние изменения (restore)
echo  9. Диагностика, шаг 1: снимок файлов (snapshot)
echo 10. Диагностика, шаг 2: что поменяла игра (diff)
echo  0. Выход
echo.
set /p c="Выбор: "
if "%c%"=="1" %PY% motorfest_tweaker.py scan --out settings_dump.txt
if "%c%"=="2" %PY% motorfest_tweaker.py apply clean_image
if "%c%"=="3" %PY% motorfest_tweaker.py apply fps_unlock
if "%c%"=="4" %PY% motorfest_tweaker.py apply fov_max
if "%c%"=="5" %PY% motorfest_tweaker.py apply clean_image fps_unlock fov_max
if "%c%"=="6" %PY% motorfest_tweaker.py lock
if "%c%"=="7" %PY% motorfest_tweaker.py unlock
if "%c%"=="8" %PY% motorfest_tweaker.py restore
if "%c%"=="9" %PY% motorfest_tweaker.py snapshot
if "%c%"=="10" (%PY% motorfest_tweaker.py diff > diff.txt & type diff.txt)
if "%c%"=="0" exit /b 0
echo.
pause
goto menu
