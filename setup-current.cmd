@echo off
setlocal
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 "%~dp0setup-current.py" %*
) else (
  where python >nul 2>nul
  if not %errorlevel%==0 (
    echo Python 3 is required. Install Python, then run this command again. 1>&2
    exit /b 1
  )
  python "%~dp0setup-current.py" %*
)
exit /b %errorlevel%
