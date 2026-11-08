@echo off
rem Sier fra (melding + lyd) når kunstappen på TV-en har sovnet. Lukk vinduet for å stoppe.
cd /d "%~dp0"
.venv\Scripts\python tv_sjekk.py --til-sovnet
pause
