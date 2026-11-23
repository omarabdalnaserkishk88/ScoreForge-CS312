@echo off
setlocal
cd /d "%~dp0"
where dotnet >nul 2>nul
if errorlevel 1 (
 echo Install Visual Studio 2022 with .NET desktop development and the .NET 8 SDK.
 pause
 exit /b 1
)
dotnet run --project desktop\ScoreForge.Desktop\ScoreForge.Desktop.csproj
pause
