@echo off
echo ========================================================
echo   TexVision AI Camera - One-Click GitHub & GitPages Push
echo ========================================================
echo.
echo Syncing docs folder for GitHub Pages...
xcopy /E /I /Y "frontend" "docs" > nul
echo.
git status
echo.
echo Adding changes...
git add .
set /p commit_msg="Enter commit message (or press ENTER for default): "
if "%commit_msg%"=="" set commit_msg=Update AI Camera and GitHub Pages - %date% %time%
git commit -m "%commit_msg%"
echo.
echo Pushing to GitHub (main branch)...
git push origin main
echo.
echo Updating gh-pages branch...
git push origin main:gh-pages --force
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Push failed! Please check your internet or git credentials.
) else (
    echo.
    echo ========================================================
    echo [SUCCESS] Code and GitPage pushed successfully to GitHub!
    echo GitPage Link: https://bhavarth007.github.io/AiCam/
    echo ========================================================
)
echo.
pause
