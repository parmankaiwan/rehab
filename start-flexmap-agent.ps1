$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonPath = Join-Path (Split-Path -Parent $projectRoot) "CV part\.venv\Scripts\python.exe"
$agentPath = Join-Path $projectRoot "local_agent.py"
if (-not (Test-Path -LiteralPath $pythonPath)) { throw "CV Python environment was not found: $pythonPath" }
if (-not (Test-Path -LiteralPath (Join-Path $projectRoot ".env.agent"))) { throw "Create .env.agent first. See .env.agent.example." }
# Start-Process joins ArgumentList values into one command line. Quote the script
# path explicitly because both repository folders contain spaces.
$quotedAgentPath = '"' + $agentPath + '"'
Start-Process -FilePath $pythonPath -ArgumentList $quotedAgentPath -WorkingDirectory $projectRoot -WindowStyle Hidden
