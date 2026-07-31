[CmdletBinding()]
param(
    [string]$FixturePdf = "",
    [string]$ApiBase = "http://localhost:5056",
    [int]$TimeoutMinutes = 180,
    [switch]$SkipBuild,
    [switch]$SkipFrontend
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$ProgressPreference = "SilentlyContinue"

$repoRoot = Split-Path -Parent $PSScriptRoot
Set-Location $repoRoot

$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$reportDir = Join-Path $repoRoot ("phase5-reports/{0}" -f $timestamp)
New-Item -ItemType Directory -Force -Path $reportDir | Out-Null

$transcriptPath = Join-Path $reportDir "phase5-transcript.log"
$summaryPath = Join-Path $reportDir "phase5-summary.json"
$composeLogPath = Join-Path $reportDir "docker-compose.log"

$summary = [ordered]@{
    started_at = (Get-Date).ToString("o")
    completed_at = $null
    result = "running"
    branch = $null
    commit = $null
    project_id = $null
    project_name = $null
    primary_source = $null
    secondary_source = $null
    checks = [ordered]@{}
    report_directory = $reportDir
    error = $null
}

function Write-Step {
    param([string]$Message)
    Write-Host ("`n=== {0} ===" -f $Message) -ForegroundColor Cyan
}

function Get-PropertyValue {
    param($Object, [string]$Name, $Default = $null)
    if ($null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name) {
        return $Object.$Name
    }
    return $Default
}

function Invoke-Native {
    param(
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    Write-Host ("> {0} {1}" -f $FilePath, ($Arguments -join " ")) -ForegroundColor DarkGray
    & $FilePath @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw ("{0} exited with code {1}" -f $FilePath, $LASTEXITCODE)
    }
}

function Invoke-Api {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $uri = if ($Path.StartsWith("http")) { $Path } else { "{0}{1}" -f $ApiBase, $Path }
    if ($Method -eq "GET") {
        return Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 60
    }
    return Invoke-RestMethod -Method Post -Uri $uri -TimeoutSec 60
}

function Wait-StackReady {
    $deadline = (Get-Date).AddMinutes(20)
    $lastDetail = "No response"

    while ((Get-Date) -lt $deadline) {
        try {
            $health = Invoke-Api -Method GET -Path "/api/drawing-extractions/multivector/health"
            $qdrantAvailable = [bool](Get-PropertyValue $health.qdrant "available" $false)
            $colsmolAvailable = [bool](Get-PropertyValue $health.colsmol "available" $false)
            if ($qdrantAvailable -and $colsmolAvailable) {
                return $health
            }
            $lastDetail = $health | ConvertTo-Json -Depth 8 -Compress
        }
        catch {
            $lastDetail = $_.Exception.Message
        }
        Start-Sleep -Seconds 5
    }

    throw ("Multi-vector stack did not become ready. Last result: {0}" -f $lastDetail)
}

function Resolve-FixturePdf {
    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($FixturePdf)) {
        $candidates.Add($FixturePdf)
    }

    $candidates.Add((Join-Path $repoRoot "Page_007_P203.pdf"))
    if (-not [string]::IsNullOrWhiteSpace($env:USERPROFILE)) {
        $candidates.Add((Join-Path $env:USERPROFILE "Downloads/Page_007_P203.pdf"))
        $candidates.Add((Join-Path $env:USERPROFILE "Desktop/Page_007_P203.pdf"))
    }

    foreach ($candidate in $candidates) {
        if (-not [string]::IsNullOrWhiteSpace($candidate) -and
            (Test-Path -LiteralPath $candidate -PathType Leaf)) {
            return (Resolve-Path -LiteralPath $candidate).Path
        }
    }

    throw (
        "Page_007_P203.pdf was not found. Save it in the repository root, your Downloads folder, " +
        "or pass -FixturePdf with its full path. Checked: {0}" -f ($candidates -join "; ")
    )
}

function Bootstrap-TestFixture {
    param([string]$LocalPdf)

    $containerId = (& docker compose ps -q construction_os).Trim()
    if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($containerId)) {
        throw "Unable to resolve the running construction_os container."
    }

    $containerPdf = "/tmp/Page_007_P203.pdf"
    Write-Host ("Fixture PDF: {0}" -f $LocalPdf)
    Invoke-Native -FilePath "docker" -Arguments @(
        "cp",
        $LocalPdf,
        ("{0}:{1}" -f $containerId, $containerPdf)
    )

    Write-Host "> docker compose exec -T construction_os bootstrap_phase5_fixture.py" -ForegroundColor DarkGray

    $savedErrorPreference = $ErrorActionPreference
    $nativePreferenceExists = Test-Path variable:PSNativeCommandUseErrorActionPreference
    $savedNativePreference = $null
    if ($nativePreferenceExists) {
        $savedNativePreference = $PSNativeCommandUseErrorActionPreference
    }

    try {
        # Python libraries may write normal debug logs to stderr. PowerShell 5 turns
        # redirected native stderr into ErrorRecord objects, so allow the process to
        # finish and decide success strictly from Docker's exit code.
        $ErrorActionPreference = "Continue"
        if ($nativePreferenceExists) {
            $PSNativeCommandUseErrorActionPreference = $false
        }

        $bootstrapOutput = @(
            & docker compose exec -T construction_os `
                /app/.venv/bin/python `
                /app/scripts/bootstrap_phase5_fixture.py `
                $containerPdf 2>&1
        )
        $bootstrapExit = $LASTEXITCODE
    }
    finally {
        $ErrorActionPreference = $savedErrorPreference
        if ($nativePreferenceExists) {
            $PSNativeCommandUseErrorActionPreference = $savedNativePreference
        }
    }

    foreach ($line in $bootstrapOutput) {
        Write-Host ([string]$line)
    }

    if ($bootstrapExit -ne 0) {
        $detail = (@($bootstrapOutput | Select-Object -Last 20) | ForEach-Object { [string]$_ }) -join "`n"
        throw ("Fixture bootstrap exited with code {0}. Output:`n{1}" -f $bootstrapExit, $detail)
    }

    $marker = $bootstrapOutput |
        Where-Object { ([string]$_).StartsWith("PHASE5_FIXTURE_JSON=") } |
        Select-Object -Last 1
    if ($null -eq $marker) {
        $detail = (@($bootstrapOutput | Select-Object -Last 20) | ForEach-Object { [string]$_ }) -join "`n"
        throw ("Fixture bootstrap completed but did not return PHASE5_FIXTURE_JSON. Output:`n{0}" -f $detail)
    }

    $prefix = "PHASE5_FIXTURE_JSON="
    $json = ([string]$marker).Substring($prefix.Length)
    return $json | ConvertFrom-Json
}

function Get-SourceStatus {
    param([string]$Pid, [string]$Sid)

    $p = [uri]::EscapeDataString($Pid)
    $s = [uri]::EscapeDataString($Sid)
    return Invoke-Api -Method GET -Path (
        "/api/drawing-extractions/multivector/projects/{0}/sources/{1}" -f $p, $s
    )
}

function Invoke-SourceAction {
    param([string]$Pid, [string]$Sid, [string]$Action)

    $p = [uri]::EscapeDataString($Pid)
    $s = [uri]::EscapeDataString($Sid)
    return Invoke-Api -Method POST -Path (
        "/api/drawing-extractions/multivector/projects/{0}/sources/{1}/{2}" -f $p, $s, $Action
    )
}

function Wait-SourceReady {
    param([string]$Pid, [string]$Sid, [string]$Label)

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $last = $null

    while ((Get-Date) -lt $deadline) {
        $last = Get-SourceStatus -Pid $Pid -Sid $Sid
        $processed = [int](Get-PropertyValue $last "processed_assets" 0)
        $total = [int](Get-PropertyValue $last "total_assets" 0)
        $points = [int](Get-PropertyValue $last "point_count" 0)
        $status = [string](Get-PropertyValue $last "status" "unknown")

        Write-Host ("{0}: {1}, points={2}, progress={3}/{4}" -f $Label, $status, $points, $processed, $total)

        if ($status -eq "ready" -and $points -gt 0) {
            return $last
        }
        if ($status -eq "error") {
            $detail = [string](Get-PropertyValue $last "last_error" "Unknown indexing error")
            throw ("{0} failed: {1}" -f $Label, $detail)
        }
        Start-Sleep -Seconds 5
    }

    $lastJson = $last | ConvertTo-Json -Depth 8 -Compress
    throw ("{0} timed out after {1} minutes. Last state: {2}" -f $Label, $TimeoutMinutes, $lastJson)
}

Start-Transcript -Path $transcriptPath -Force | Out-Null
try {
    Write-Step "Record repository state"
    $summary.branch = (& git branch --show-current).Trim()
    $summary.commit = (& git rev-parse HEAD).Trim()
    Write-Host ("Branch: {0}" -f $summary.branch)
    Write-Host ("Commit: {0}" -f $summary.commit)

    if ($summary.branch -ne "multi-vector") {
        throw ("Run this script from the multi-vector branch, not '{0}'." -f $summary.branch)
    }

    if (-not $SkipBuild) {
        Write-Step "Build Phase 5 services"
        Invoke-Native -FilePath "docker" -Arguments @(
            "compose", "build", "construction_os", "colsmol"
        )
        $summary.checks["build"] = "passed"
    }
    else {
        $summary.checks["build"] = "skipped"
    }

    Write-Step "Start isolated stack"
    Invoke-Native -FilePath "docker" -Arguments @(
        "compose", "up", "-d", "qdrant", "colsmol", "construction_os"
    )
    $health = Wait-StackReady
    $summary.checks["stack_health"] = [ordered]@{
        result = "passed"
        qdrant = [string](Get-PropertyValue $health.qdrant "status" "unknown")
        colsmol = [string](Get-PropertyValue $health.colsmol "status" "unknown")
        gpu = Get-PropertyValue (Get-PropertyValue $health.colsmol "detail") "gpu_name"
    }

    Write-Step "Ensure Qdrant multi-vector collection"
    $summary.checks["collection"] = Invoke-Api -Method POST -Path "/api/drawing-extractions/multivector/collection/ensure"

    Write-Step "Run ColSmol service contract tests"
    Invoke-Native -FilePath "docker" -Arguments @(
        "compose", "exec", "-T", "colsmol", "pytest", "-q", "tests/test_contract.py"
    )
    $summary.checks["colsmol_contract_tests"] = "passed"

    Write-Step "Run Phase 5 backend and regression tests"
    Invoke-Native -FilePath "docker" -Arguments @(
        "compose", "run", "--rm", "--no-deps", "-e", "UV_NO_SYNC=0",
        "construction_os", "uv", "run", "--group", "dev", "pytest", "-q",
        "tests/test_qdrant_integration.py",
        "tests/test_colsmol_integration.py",
        "tests/test_multivector_store.py",
        "tests/test_multivector_state.py",
        "tests/test_multivector_indexer.py",
        "tests/test_multivector_indexer_isolation.py"
    )
    $summary.checks["backend_tests"] = "passed"

    if (-not $SkipFrontend) {
        Write-Step "Run visual-index frontend tests"
        Invoke-Native -FilePath "docker" -Arguments @(
            "build", "--target", "builder", "-t", "construction-os-multivector-test", "."
        )
        Invoke-Native -FilePath "docker" -Arguments @(
            "run", "--rm", "construction-os-multivector-test", "sh", "-lc",
            "cd /app/frontend && npm test -- src/components/multivector/ProjectMultiVectorDialog.test.tsx"
        )
        $summary.checks["frontend_tests"] = "passed"
    }
    else {
        $summary.checks["frontend_tests"] = "skipped"
    }

    Write-Step "Create Test project and attach the supplied P203 drawing PDF"
    $localFixture = Resolve-FixturePdf
    $fixture = Bootstrap-TestFixture -LocalPdf $localFixture

    $projectId = [string](Get-PropertyValue $fixture "project_id" "")
    $projectName = [string](Get-PropertyValue $fixture "project_name" "Test")
    $sourceId = [string](Get-PropertyValue $fixture "source_id" "")
    $sourceTitle = [string](Get-PropertyValue $fixture "source_title" "Page_007_P203.pdf")
    $storedPath = [string](Get-PropertyValue $fixture "file_path" "")

    if ([string]::IsNullOrWhiteSpace($projectId) -or [string]::IsNullOrWhiteSpace($sourceId)) {
        throw ("Fixture bootstrap returned invalid IDs: {0}" -f ($fixture | ConvertTo-Json -Depth 8 -Compress))
    }

    $summary.project_id = $projectId
    $summary.project_name = $projectName
    $summary.primary_source = [ordered]@{
        id = $sourceId
        title = $sourceTitle
        file_path = $storedPath
        file_size = [int](Get-PropertyValue $fixture "file_size" 0)
        file_hash = [string](Get-PropertyValue $fixture "file_hash" "")
    }
    $summary.checks["fixture_bootstrap"] = "passed"

    Write-Host ("Project: {0} [{1}]" -f $projectName, $projectId)
    Write-Host ("Source: {0} [{1}]" -f $sourceTitle, $sourceId)
    Write-Host ("Stored PDF: {0}" -f $storedPath)

    Write-Step "Index primary PDF using the same enable action as the UI icon"
    $queued = Invoke-SourceAction -Pid $projectId -Sid $sourceId -Action "enable"
    Write-Host ($queued | ConvertTo-Json -Depth 8)
    $ready = Wait-SourceReady -Pid $projectId -Sid $sourceId -Label "Primary enable"
    $summary.primary_source["first_ready_points"] = [int](Get-PropertyValue $ready "point_count" 0)
    $summary.checks["primary_enable"] = "passed"

    Write-Step "Disable primary PDF"
    $disabled = Invoke-SourceAction -Pid $projectId -Sid $sourceId -Action "disable"
    if ([string](Get-PropertyValue $disabled "status" "") -ne "disabled" -or
        [bool](Get-PropertyValue $disabled "enabled" $true)) {
        throw ("Disable verification failed: {0}" -f ($disabled | ConvertTo-Json -Depth 8 -Compress))
    }
    $summary.checks["primary_disable"] = "passed"

    Write-Step "Re-enable primary PDF"
    $null = Invoke-SourceAction -Pid $projectId -Sid $sourceId -Action "enable"
    $readyAgain = Wait-SourceReady -Pid $projectId -Sid $sourceId -Label "Primary re-enable"
    $summary.primary_source["reenabled_points"] = [int](Get-PropertyValue $readyAgain "point_count" 0)
    $summary.checks["primary_reenable"] = "passed"

    Write-Step "Clean rebuild primary PDF"
    $rebuild = Invoke-SourceAction -Pid $projectId -Sid $sourceId -Action "rebuild"
    Write-Host ($rebuild | ConvertTo-Json -Depth 8)
    $rebuilt = Wait-SourceReady -Pid $projectId -Sid $sourceId -Label "Primary rebuild"
    $summary.primary_source["rebuilt_points"] = [int](Get-PropertyValue $rebuilt "point_count" 0)
    $summary.checks["primary_rebuild"] = "passed"

    Write-Warning "The fixture contains one PDF. Real second-source verification is skipped; automated two-source isolation coverage remains active."
    $summary.secondary_source = [ordered]@{
        result = "skipped"
        reason = "The supplied Test fixture contains one PDF"
        automated_coverage = "tests/test_multivector_indexer_isolation.py"
    }
    $summary.checks["secondary_independence"] = "covered_by_automated_test"

    Write-Step "Final health verification"
    $finalHealth = Wait-StackReady
    $summary.checks["final_health"] = [ordered]@{
        result = "passed"
        qdrant = [string](Get-PropertyValue $finalHealth.qdrant "status" "unknown")
        colsmol = [string](Get-PropertyValue $finalHealth.colsmol "status" "unknown")
    }

    $summary.result = "passed"
    Write-Host "`nPHASE 5 VERIFICATION PASSED" -ForegroundColor Green
}
catch {
    $summary.result = "failed"
    $summary.error = $_.Exception.Message
    Write-Host ("`nPHASE 5 VERIFICATION FAILED: {0}" -f $summary.error) -ForegroundColor Red
}
finally {
    $summary.completed_at = (Get-Date).ToString("o")
    $summary | ConvertTo-Json -Depth 12 | Out-File -FilePath $summaryPath -Encoding utf8

    try {
        & docker compose logs --no-color --tail=400 construction_os colsmol qdrant |
            Out-File -FilePath $composeLogPath -Encoding utf8
    }
    catch {
        Write-Warning ("Could not collect Docker logs: {0}" -f $_.Exception.Message)
    }

    Stop-Transcript | Out-Null
    Write-Host ("Summary: {0}" -f $summaryPath)
    Write-Host ("Transcript: {0}" -f $transcriptPath)
    Write-Host ("Docker logs: {0}" -f $composeLogPath)
}

if ($summary.result -ne "passed") { exit 1 }
exit 0
