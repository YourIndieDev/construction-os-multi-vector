[CmdletBinding()]
param(
    [string]$ApiBase = "http://localhost:5056",
    [string]$Query = "architectural floor plan main entrance doors rooms and dimensions",
    [switch]$SkipBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = Join-Path $repoRoot "phase6-reports/$timestamp"
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null
$summaryPath = Join-Path $reportDir "phase6-summary.json"
$transcriptPath = Join-Path $reportDir "phase6-transcript.log"
$composeLogPath = Join-Path $reportDir "docker-compose.log"

$summary = [ordered]@{
    started_at = (Get-Date).ToString("o")
    completed_at = $null
    result = "running"
    branch = $null
    commit = $null
    phase5_summary = $null
    project_id = $null
    source_id = $null
    query = $Query
    result_count = 0
    top_result = $null
    checks = [ordered]@{}
    error = $null
}

function Write-Step([string]$Message) {
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )
    Write-Host "> $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "$FilePath exited with code $LASTEXITCODE"
    }
}

function Invoke-ApiGet([string]$Path) {
    return Invoke-RestMethod -Method Get -Uri "$ApiBase$Path" -TimeoutSec 60
}

function Invoke-ApiPost([string]$Path, [hashtable]$Body) {
    return Invoke-RestMethod `
        -Method Post `
        -Uri "$ApiBase$Path" `
        -ContentType "application/json" `
        -Body ($Body | ConvertTo-Json -Depth 12) `
        -TimeoutSec 300
}

function Wait-StackReady {
    $deadline = (Get-Date).AddMinutes(20)
    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-ApiGet "/api/drawing-extractions/multivector/health"
            if ($health.qdrant.available -and $health.colsmol.available) {
                return $health
            }
        } catch {}
        Start-Sleep -Seconds 5
    }
    throw "Qdrant and ColSmol did not become ready."
}

Start-Transcript -Path $transcriptPath -Force | Out-Null
try {
    Write-Step "Require a successful Phase 5 report"
    $phase5File = Get-ChildItem -Path (Join-Path $repoRoot "phase5-reports") `
        -Filter "phase5-summary.json" -File -Recurse -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $phase5File) {
        throw "No Phase 5 summary was found. Complete scripts/verify-phase5.ps1 first."
    }
    $phase5 = Get-Content $phase5File.FullName -Raw | ConvertFrom-Json
    if ($phase5.result -ne "passed") {
        throw "Latest Phase 5 result is '$($phase5.result)', not passed: $($phase5File.FullName)"
    }
    $summary.phase5_summary = $phase5File.FullName
    $summary.project_id = $phase5.project_id
    $summary.checks.phase5_gate = "passed"

    Write-Step "Record repository state"
    $summary.branch = (& git branch --show-current).Trim()
    $summary.commit = (& git rev-parse HEAD).Trim()
    if ($summary.branch -ne "multi-vector") {
        throw "Run this script from the multi-vector branch."
    }

    if (-not $SkipBuild) {
        Write-Step "Build Phase 6 application"
        Invoke-Native -FilePath "docker" -Arguments @(
            "compose", "build", "construction_os"
        )
        $summary.checks.build = "passed"
    } else {
        $summary.checks.build = "skipped"
    }

    Write-Step "Start and verify the isolated stack"
    Invoke-Native -FilePath "docker" -Arguments @(
        "compose", "up", "-d", "qdrant", "colsmol", "construction_os"
    )
    $health = Wait-StackReady
    $summary.checks.stack_health = [ordered]@{
        result = "passed"
        qdrant = $health.qdrant.status
        colsmol = $health.colsmol.status
    }

    Write-Step "Run Phase 6 unit and regression tests"
    Invoke-Native -FilePath "docker" -Arguments @(
        "compose", "run", "--rm", "--no-deps", "-e", "UV_NO_SYNC=0",
        "construction_os", "uv", "run", "--group", "dev", "pytest", "-q",
        "tests/test_colsmol_query.py",
        "tests/test_multivector_search.py",
        "tests/test_multivector_project_status.py",
        "tests/test_multivector_retrieval.py",
        "tests/test_multivector_search_api.py",
        "tests/test_multivector_store.py",
        "tests/test_multivector_state.py"
    )
    $summary.checks.tests = "passed"

    Write-Step "Select an enabled ready source"
    $projectId = [string]$summary.project_id
    if (-not $projectId) {
        throw "The Phase 5 report did not contain project_id."
    }
    $projectEscaped = [uri]::EscapeDataString($projectId)
    $sourceResponse = Invoke-ApiGet "/api/drawing-extractions/multivector/projects/$projectEscaped/sources"
    $readySources = @($sourceResponse.sources | Where-Object {
        $_.enabled -and $_.status -eq "ready" -and [int]$_.point_count -gt 0
    })
    if ($readySources.Count -lt 1) {
        throw "No enabled ready visual-index source was found in project $projectId."
    }
    $sourceId = [string]$readySources[0].source_id
    $summary.source_id = $sourceId

    Write-Step "Run a real ColSmol to Qdrant visual search"
    $stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
    $search = Invoke-ApiPost "/api/drawing-extractions/multivector/search" @{
        query = $Query
        project_id = $projectId
        source_ids = @($sourceId)
        limit = 10
    }
    $stopwatch.Stop()

    if ($search.mode -ne "multi_vector") {
        throw "Unexpected retrieval mode: $($search.mode)"
    }
    if ([int]$search.result_count -lt 1) {
        throw "The real multi-vector search returned no results."
    }

    $results = @($search.results)
    foreach ($result in $results) {
        if ([string]$result.parent_id -ne $sourceId) {
            throw "Source filter failed. Result $($result.id) belongs to $($result.parent_id)."
        }
        if (-not $result.multi_vector -or $result.retrieval_backend -ne "qdrant_maxsim") {
            throw "Result $($result.id) is missing multi-vector evidence markers."
        }
        if (-not $result.evidence_crop) {
            throw "Result $($result.id) has no evidence image path."
        }
    }

    $pageKeys = @($results | ForEach-Object {
        "$($_.source_id)|$($_.page_index)"
    })
    if (@($pageKeys | Select-Object -Unique).Count -ne $pageKeys.Count) {
        throw "Page-level overlap deduplication failed."
    }

    $summary.result_count = [int]$search.result_count
    $summary.top_result = $results[0]
    $summary.checks.real_query = [ordered]@{
        result = "passed"
        duration_ms = $stopwatch.ElapsedMilliseconds
        returned = [int]$search.result_count
    }
    $summary.checks.source_filter = "passed"
    $summary.checks.page_deduplication = "passed"
    $summary.result = "passed"
    Write-Host "`nPHASE 6 VERIFICATION PASSED" -ForegroundColor Green
}
catch {
    $summary.result = "failed"
    $summary.error = $_.Exception.Message
    Write-Host "`nPHASE 6 VERIFICATION FAILED: $($summary.error)" -ForegroundColor Red
}
finally {
    $summary.completed_at = (Get-Date).ToString("o")
    $summary | ConvertTo-Json -Depth 14 | Out-File -FilePath $summaryPath -Encoding utf8
    try {
        & docker compose logs --no-color --tail=400 construction_os colsmol qdrant |
            Out-File -FilePath $composeLogPath -Encoding utf8
    } catch {}
    Stop-Transcript | Out-Null
    Write-Host "Summary: $summaryPath"
    Write-Host "Transcript: $transcriptPath"
    Write-Host "Docker logs: $composeLogPath"
}

if ($summary.result -ne "passed") { exit 1 }
exit 0
