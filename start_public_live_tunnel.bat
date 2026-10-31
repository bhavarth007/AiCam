@echo off
title AiCam Camera - Public Live Cloud Access
echo ========================================================
echo   AiCam Camera - Cloud Access Portal
echo   Sharing local AI Vision stream securely to the Internet
echo ========================================================
echo.
echo Starting Cloudflare Live Tunnel connected to port 8000...
echo Keep this window open while you want external cloud access!
echo.
"%~dp0tools\cloudflared.exe" tunnel --url http://127.0.0.1:8000
pause
