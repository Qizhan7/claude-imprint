# ─── Imprint Cron Task Runner (Windows) ───
# Runs a claude CLI task with imprint-memory MCP only (no telegram/wechat plugins).
# Usage: cron-task.ps1 <task-name> <prompt-file>
#
# Setup: Create a Windows Task Scheduler task that runs:
#   powershell -ExecutionPolicy Bypass -File C:\path\to\cron-task.ps1 morning-briefing C:\path\to\cron-prompts\morning-briefing.md
#
# Design decisions:
#   - Runs from $HOME to avoid loading project-level .mcp.json
#   - Uses cron-mcp.json with only imprint-memory
#   - Captures AI output; if telegram was sent, appends to recent_context.md
#   - --max-budget-usd caps cost; CLI exits naturally after completion

param(
    [Parameter(Mandatory)][string]$TaskName,
    [Parameter(Mandatory)][string]$PromptFile
)

$ErrorActionPreference = "Stop"

$ProjectDir = if ($env:IMPRINT_PROJECT_DIR) { $env:IMPRINT_PROJECT_DIR } else { Split-Path -Parent $MyInvocation.MyCommand.Path }
$LogDir = Join-Path $ProjectDir "logs"
$ContextFile = Join-Path $ProjectDir "recent_context.md"
$McpConfig = Join-Path $ProjectDir "cron-mcp.json"

# ─── Auth ───
# Max Plan users: store your OAuth token in ~/.claude/cron-token
# API key users: store your key in ~/.claude/cron-token and set ANTHROPIC_API_KEY instead
$TokenFile = Join-Path $env:USERPROFILE ".claude\cron-token"
if (Test-Path $TokenFile) {
    $env:CLAUDE_CODE_OAUTH_TOKEN = (Get-Content $TokenFile -Raw).Trim()
    # $env:ANTHROPIC_API_KEY = (Get-Content $TokenFile -Raw).Trim()  # uncomment for API key auth
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogFile = Join-Path $LogDir "cron-$TaskName.log"

# ─── Timestamp ───
$TS = Get-Date -Format "yyyy-MM-dd HH:mm"
$TSShort = Get-Date -Format "MM-dd HH:mm"

Add-Content $LogFile "[$TS] === $TaskName start ==="

# ─── Read prompt ───
if (-not (Test-Path $PromptFile)) {
    Add-Content $LogFile "[$TS] ERROR: prompt file not found: $PromptFile"
    exit 1
}
$Prompt = Get-Content $PromptFile -Raw

# ─── Run claude CLI ───
# Run from HOME to avoid loading project-level .mcp.json
$TmpOut = [System.IO.Path]::GetTempFileName()
Push-Location $env:USERPROFILE
try {
    $Prompt | claude -p --mcp-config $McpConfig --dangerously-skip-permissions --max-budget-usd 0.50 --output-format text 2>> $LogFile > $TmpOut
} catch {
    # claude may exit non-zero; continue to capture output
}
Pop-Location

$Output = if (Test-Path $TmpOut) { Get-Content $TmpOut -Raw } else { "" }
Remove-Item $TmpOut -ErrorAction SilentlyContinue

$OutputPreview = if ($Output.Length -gt 200) { $Output.Substring(0, 200) } else { $Output }
Add-Content $LogFile "[$TS] Output: $OutputPreview"

# ─── Append to recent_context.md if telegram was sent ───
$SentLine = ($Output -split "`n") | Where-Object { $_ -match "^SENT_TG:" } | Select-Object -First 1
if ($SentLine) {
    $SentMsg = ($SentLine -replace "^SENT_TG:\s*", "").Trim()
    $Display = if ($SentMsg.Length -gt 200) { $SentMsg.Substring(0, 200) } else { $SentMsg }

    # Write to conversation_log DB via Python (parameterized queries, no SQL injection)
    $DbTS = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
    $LogScript = Join-Path $ProjectDir "scripts\log_conversation.py"
    try {
        python3 $LogScript `
            --platform telegram --direction out --speaker Agent `
            --content $Display --session "cron-$TaskName" --entrypoint cron `
            --created-at $DbTS 2>> $LogFile
    } catch {
        Add-Content $LogFile "[$TS] WARN: log_conversation.py failed"
    }

    # Append to recent_context.md
    Add-Content $ContextFile "[$TSShort tg/out] $Display"
    Add-Content $LogFile "[$TS] Logged to DB + appended to recent_context: $Display"
}

# Sync recent_context.md -> CLAUDE.md AUTO section
try {
    python3 (Join-Path $ProjectDir "update_claude_md.py") 2>> $LogFile >> $LogFile
} catch {
    # optional, may not be configured
}

Add-Content $LogFile "[$TS] === $TaskName done ==="
