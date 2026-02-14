@echo off
echo Creating virtual environment...
python -m venv venv

echo Activating virtual environment and installing dependencies...
call venv\Scripts\activate.bat
cd script
pip install -r requirements.txt

echo Installation complete.
pause