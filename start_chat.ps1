Set-Location -LiteralPath $PSScriptRoot
& "$PSScriptRoot\.venv\Scripts\python.exe" -X utf8 -m streamlit run "$PSScriptRoot\app\streamlit_app.py"
