@echo off
echo ========================================================
echo   TexVision AI Camera - One-Click GitHub Push
echo ========================================================
echo.
git status
echo.
echo Adding changes...
git add .
set /p commit_msg="Enter commit message (or press ENTER for default): "
if "%commit_msg%"=="" set commit_msg=Update AI Camera codebase - %date% %time%
git commit -m "%commit_msg%"
echo.
echo Pushing to GitHub (main branch)...
git push origin main
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Push failed! Please make sure your GitHub repo exists:
    echo https://github.com/bhavarthhapani/AiCam
    echo If you have not created it yet, create an empty repo named "AiCam" on GitHub:
    echo https://github.com/new
) else (
    echo.
    echo [SUCCESS] Code pushed successfully to GitHub!
)
echo.
pause
