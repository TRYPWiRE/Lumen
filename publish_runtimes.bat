@echo off
setlocal
cd /d "%~dp0"
rem Builds the runtime packs (Qt web engine, AI engine) that some extensions download once,
rem uploads them to the GitHub pre-release "runtimes" and pushes updates\manifest.json.
rem Run this the first time, and again whenever you change the PyQt6 version in requirements.txt.
for /f "delims=" %%r in ('python -c "from lumen import config; print(config.GITHUB_OWNER + '/' + config.GITHUB_REPO)"') do set REPO=%%r
where gh >nul 2>nul || (echo GitHub CLI "gh" not found - install it from https://cli.github.com & goto :error)

echo === Building runtime packs (downloads ~170 MB of wheels) ===
python -m pip install pefile >nul
python tools\build_runtimes.py || goto :error

gh release view runtimes --repo %REPO% >nul 2>nul
if errorlevel 1 (
    gh release create runtimes --repo %REPO% --prerelease --title "Runtime packs" --notes "Libraries that Lumen extensions download once (web engine, AI engine). Not an app release." || goto :error
)
gh release upload runtimes release\runtimes\*.zip --repo %REPO% --clobber || goto :error

git add updates\manifest.json || goto :error
git commit -m "Update runtime packs" || echo Nothing new to commit.
git push || goto :error
echo.
echo Runtime packs published.
pause
exit /b 0
:error
echo.
echo Publishing stopped - see the message above.
pause
exit /b 1
