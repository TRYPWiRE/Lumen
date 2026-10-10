@echo off
setlocal
cd /d "%~dp0"
rem Publishes the version built by build.bat:
rem   1. creates GitHub release v<version> with the installer attached
rem   2. commits + pushes updates\manifest.json and extension zips (the app reads these on startup)
rem Needs: git and the GitHub CLI (https://cli.github.com). Sign-in and repo setup are handled below.

for /f "delims=" %%v in ('python -c "import lumen; print(lumen.__version__)"') do set VER=%%v
for /f "delims=" %%r in ('python -c "from lumen import config; print(config.GITHUB_OWNER + '/' + config.GITHUB_REPO)"') do set REPO=%%r

if not exist "release\LumenSetup-%VER%.exe" (
    echo release\LumenSetup-%VER%.exe not found - run build.bat first.
    goto :error
)
where git >nul 2>nul || (echo Git not found - install it from https://git-scm.com & goto :error)
where gh >nul 2>nul || (echo GitHub CLI "gh" not found - install it from https://cli.github.com & goto :error)

rem --- 1. Sign in to GitHub (first time only) ---
gh auth status >nul 2>nul
if errorlevel 1 (
    echo You're not signed in to GitHub yet. A browser window will open to sign in.
    echo When asked, choose: GitHub.com  ^>  HTTPS  ^>  Yes ^(authenticate Git^)  ^>  Login with a web browser
    echo.
    gh auth login --hostname github.com --git-protocol https --web || goto :error
)
gh auth setup-git >nul 2>nul

rem --- 2. Make sure this folder is a git repo connected to %REPO% (first time only) ---
if not exist ".git" (
    git init -b main || goto :error
)
git remote get-url origin >nul 2>nul
if errorlevel 1 (
    gh repo view %REPO% >nul 2>nul
    if errorlevel 1 (
        echo Creating public repo https://github.com/%REPO% ...
        gh repo create %REPO% --public --description "Lumen - a Photoshop-style image editor" || goto :error
    )
    git remote add origin https://github.com/%REPO%.git || goto :error
)

rem --- 3. Push the code first so the release has something to tag ---
rem Git needs a name/email for commits; use your GitHub account if none is set yet.
git config user.email >nul 2>nul
if errorlevel 1 (
    for /f "delims=" %%u in ('gh api user --jq .login') do (
        git config user.name "%%u"
        git config user.email "%%u@users.noreply.github.com"
    )
)
git add -A || goto :error
git commit -m "Release Lumen %VER%" >nul 2>nul || echo Nothing new to commit.
git push -u origin HEAD:main || goto :error

rem --- 4. Create (or refresh) the GitHub release with the installer ---
gh release view v%VER% --repo %REPO% >nul 2>nul
if errorlevel 1 (
    gh release create v%VER% "release\LumenSetup-%VER%.exe" --repo %REPO% --target main --title "Lumen %VER%" --notes "Lumen %VER%" || goto :error
) else (
    gh release upload v%VER% "release\LumenSetup-%VER%.exe" --repo %REPO% --clobber || goto :error
)

echo.
echo Published Lumen %VER% to https://github.com/%REPO%
echo Installed copies will offer the update next time they start.
pause
exit /b 0
:error
echo.
echo Publishing stopped - see the message above.
pause
exit /b 1
