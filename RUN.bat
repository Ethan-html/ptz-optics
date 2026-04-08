@echo off
cd /d %~dp0

echo Starting server at http://localhost:8080
echo Press CTRL+C to stop
start http://localhost:8080
python app.py


pause