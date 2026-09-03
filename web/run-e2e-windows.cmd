@echo off
setlocal
cd /d D:\Stuff\Projects\Sites\Planora\web
set "PLAYWRIGHT_SKIP_WEBSERVER=1"
set "PLAYWRIGHT_BASE_URL=http://127.0.0.1:4173"
set "PLAYWRIGHT_BROWSER_EXECUTABLE=C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
call C:\Progra~1\nodejs\npm.cmd run build
if errorlevel 1 exit /b %errorlevel%
"C:\Program Files\nodejs\node.exe" node_modules\@playwright\test\cli.js test --config playwright.config.ts --reporter=line
