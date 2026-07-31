[CmdletBinding()]
param(
    [string]$ProjectId = "",
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
$reportDir = Join-Path $repoRoot "phase5-reports/$timestamp"
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
    Write-Host "`n=== $Message ===" -ForegroundColor Cyan
}

function Has-Property {
    param($Object, [string]$Name)
    return $null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name
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

function Invoke-Api {
    param(
        [Parameter(Mandatory = $true)][ValidateSet("GET", "POST")][string]$Method,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $uri = if ($Path.StartsWith("http")) { $Path } else { "$ApiBase$Path" }
    if ($Method -eq "GET") {
        return Invoke-RestMethod -Method Get -Uri $uri -TimeoutSec 60
    }
    return Invoke-RestMethod -Method Post -Uri $uri -TimeoutSec 60
}

function Wait-StackReady {
    $deadline = (Get-Date).AddMinutes(20)
    $last = $null

    while ((Get-Date) -lt $deadline) {
        try {
            $last = Invoke-Api -Method GET -Path "/api/drawing-extractions/multivector/health"
            if ($last.qdrant.available -and $last.colsmol.available) {
                return $last
            }
        }
        catch {
            $last = $_.Exception.Message
        }
        Start-Sleep -Seconds 5
    }

    throw "Multi-vector stack did not become ready. Last result: $($last | ConvertTo-Json -Depth 8 -Compress)"
}

function Get-SourceStatus {
    param([string]$Pid, [string]$Sid)

    $p = [uri]::EscapeDataString($Pid)
    $s = [uri]::EscapeDataString($Sid)
    return Invoke-Api -Method GET -Path "/api/drawing-extractions/multivector/projects/$p/sources/$s"
}

function Invoke-SourceAction {
    param([string]$Pid, [string]$Sid, [string]$Action)

    $p = [uri]::EscapeDataString($Pid)
    $s = [uri]::EscapeDataString($Sid)
    return Invoke-Api -Method POST -Path "/api/drawing-extractions/multivector/projects/$p/sources/$s/$Action"
}

function Wait-SourceReady {
    param([string]$Pid, [string]$Sid, [string]$Label)

    $deadline = (Get-Date).AddMinutes($TimeoutMinutes)
    $last = $null

    while ((Get-Date) -lt $deadline) {
        $last = Get-SourceStatus -Pid $Pid -Sid $Sid
        $processed = if (Has-Property $last "processed_assets") { [int]$last.processed_assets } else { 0 }
        $total = if (Has-Property $last "total_assets") { [int]$last.total_assets } else { 0 }
        $points = if (Has-Property $last "point_count") { [int]$last.point_count } else { 0 }
        $status = if (Has-Property $last "status") { [string]$last.status } else { "unknown" }

        Write-Host "${Label}: $status, points=$points, progress=$processed/$total"

        if ($status -eq "ready" -and $points -gt 0) {
            return $last
        }
        if ($status -eq "error") {
            $detail = if (Has-Property $last "last_error") { [string]$last.last_error } else { "Unknown indexing error" }
            throw "$Label failed: $detail"
        }
        Start-Sleep -Seconds 5
    }

    throw "$Label timed out after $TimeoutMinutes minutes. Last state: $($last | ConvertTo-Json -Depth 8 -Compress)"
}

function Get-EligibleSources {
    param([string]$Pid)

    $p = [uri]::EscapeDataString($Pid)
    $response = Invoke-Api -Method GET -Path "/api/drawing-extractions/multivector/projects/$p/sources"
    $sources = if (Has-Property $response "sources") { @($response.sources) } else { @($response) }

    return @($sources | Where-Object {
        (Has-Property $_ "current_file_hash") -and
        -not [string]::IsNullOrWhiteSpace([string]$_.current_file_hash) -and
        (-not (Has-Property $_ "file_error") -or [string]::IsNullOrWhiteSpace([string]$_.file_error))
    })
}

function Get-Projects {
    $response = Invoke-Api -Method GET -Path "/api/projects?archived=false&order_by=updated%20desc"

    if (Has-Property $response "projects") {
        return @($response.projects)
    }
    if (Has-Property $response "results") {
        return @($response.results)
    }
    return @($response)
}

Start-Transcript -Path $transcriptPath -Force | Out-Null
try {
    Write-Step "Record repository state"
    $summary.branch = (& git branch --show-current).Trim()
    $summary.commit = (& git rev-parse HEAD).Trim()
    Write-Host "Branch: $($summary.branch)"
    Write-Host "Commit: $($summary.commit)"

    if ($summary.branch -ne "multi-vector") {
        throw "Run this script from the multi-vector branch, not '$($summary.branch)'."
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
        qdrant = $health.qdrant.status
        colsmol = $health.colsmol.status
        gpu = $health.colsmol.detail.gpu_name
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

    Write-Step "Select a project with eligible uploaded PDFs"
    $projects = @(Get-Projects)
    $selectedProject = $null
    $eligible = @()

    if (-not [string]::IsNullOrWhiteSpace($ProjectId)) {
        $selectedProject = $projects | Where-Object {
            (Has-Property $_ "id") -and [string]$_.id -eq $ProjectId
        } | Select-Object -First 1

        if ($null -eq $selectedProject) {
            throw "Project '$ProjectId' was not returned by the projects API."
        }
        $eligible = @(Get-EligibleSources -Pid $ProjectId)
    }
    else {
        foreach ($project in $projects) {
            if (-not (Has-Property $project "id")) {
                continue
            }

            $candidateProjectId = [string]$project.id
            if ([string]::IsNullOrWhiteSpace($candidateProjectId)) {
                continue
            }

            try {
                $candidate = @(Get-EligibleSources -Pid $candidateProjectId)
                Write-Host "Checked project $candidateProjectId: $($candidate.Count) eligible PDF source(s)"
                if ($candidate.Count -gt 0) {
                    $selectedProject = $project
                    $eligible = $candidate
                    break
                }
            }
            catch {
                Write-Warning "Skipping project $candidateProjectId: $($_.Exception.Message)"
            }
        }
    }

    if ($null -eq $selectedProject -or $eligible.Count -eq 0) {
        throw "No project containing an accessible uploaded PDF was found."
    }

    $selectedProjectId = [string]$selectedProject.id
    $selectedProjectName = if (Has-Property $selectedProject "name") { [string]$selectedProject.name } else { $selectedProjectId }
    $summary.project_id = $selectedProjectId
    $summary.project_name = $selectedProjectName
    Write-Host "Project: $selectedProjectName [$selectedProjectId]"
    Write-Host "Eligible PDFs: $($eligible.Count)"

    $primary = $eligible[0]
    $primaryId = [string]$primary.source_id
    $primaryTitle = if (Has-Property $primary "source_title") { [string]$primary.source_title } else { $primaryId }
    $summary.primary_source = [ordered]@{
        id = $primaryId
        title = $primaryTitle
    }

    Write-Step "Index primary PDF using the same enable action as the UI icon"
    $queued = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "enable"
    Write-Host ($queued | ConvertTo-Json -Depth 8)
    $ready = Wait-SourceReady -Pid $selectedProjectId -Sid $primaryId -Label "Primary enable"
    $summary.primary_source["first_ready_points"] = [int]$ready.point_count
    $summary.checks["primary_enable"] = "passed"

    Write-Step "Disable primary PDF"
    $disabled = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "disable"
    if ([string]$disabled.status -ne "disabled" -or [bool]$disabled.enabled) {
        throw "Disable verification failed: $($disabled | ConvertTo-Json -Depth 8 -Compress)"
    }
    $summary.checks["primary_disable"] = "passed"

    Write-Step "Re-enable primary PDF"
    $null = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "enable"
    $readyAgain = Wait-SourceReady -Pid $selectedProjectId -Sid $primaryId -Label "Primary re-enable"
    $summary.primary_source["reenabled_points"] = [int]$readyAgain.point_count
    $summary.checks["primary_reenable"] = "passed"

    Write-Step "Clean rebuild primary PDF"
    $rebuild = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "rebuild"
    Write-Host ($rebuild | ConvertTo-Json -Depth 8)
    $rebuilt = Wait-SourceReady -Pid $selectedProjectId -Sid $primaryId -Label "Primary rebuild"
    $summary.primary_source["rebuilt_points"] = [int]$rebuilt.point_count
    $summary.checks["primary_rebuild"] = "passed"

    if ($eligible.Count -gt 1) {
        Write-Step "Index a second PDF independently"
        $secondary = $eligible[1]
        $secondaryId = [string]$secondary.source_id
        $secondaryTitle = if (Has-Property $secondary "source_title") { [string]$secondary.source_title } else { $secondaryId }
        $summary.secondary_source = [ordered]@{
            id = $secondaryId
            title = $secondaryTitle
        }

        $null = Invoke-SourceAction -Pid $selectedProjectId -Sid $secondaryId -Action "enable"
        $secondaryReady = Wait-SourceReady -Pid $selectedProjectId -Sid $secondaryId -Label "Secondary enable"
        $primaryStillReady = Get-SourceStatus -Pid $selectedProjectId -Sid $primaryId

        if ([string]$primaryStillReady.status -ne "ready" -or [int]$primaryStillReady.point_count -lt 1) {
            throw "Primary source was disturbed while indexing the secondary source."
        }

        $summary.secondary_source["ready_points"] = [int]$secondaryReady.point_count
        $summary.checks["secondary_independence"] = "passed"
    }
    else {
        Write-Warning "Only one eligible PDF exists in this project. Real second-source verification was skipped; two-source isolation remains covered by the automated test suite."
        $summary.secondary_source = [ordered]@{
            result = "skipped"
            reason = "Only one eligible PDF was available"
            automated_coverage = "tests/test_multivector_indexer_isolation.py"
        }
        $summary.checks["secondary_independence"] = "covered_by_automated_test"
    }

    Write-Step "Final health verification"
    $finalHealth = Wait-StackReady
    $summary.checks["final_health"] = [ordered]@{
        result = "passed"
        qdrant = $finalHealth.qdrant.status
        colsmol = $finalHealth.colsmol.status
    }

    $summary.result = "passed"
    Write-Host "`nPHASE 5 VERIFICATION PASSED" -ForegroundColor Green
}
catch {
    $summary.result = "failed"
    $summary.error = $_.Exception.Message
    Write-Host "`nPHASE 5 VERIFICATION FAILED: $($summary.error)" -ForegroundColor Red
}
finally {
    $summary.completed_at = (Get-Date).ToString("o")
    $summary | ConvertTo-Json -Depth 12 | Out-File -FilePath $summaryPath -Encoding utf8

    try {
        & docker compose logs --no-color --tail=400 construction_os colsmol qdrant |
            Out-File -FilePath $composeLogPath -Encoding utf8
    }
    catch {
        Write-Warning "Could not collect Docker logs: $($_.Exception.Message)"
    }

    Stop-Transcript | Out-Null
    Write-Host "Summary: $summaryPath"
    Write-Host "Transcript: $transcriptPath"
    Write-Host "Docker logs: $composeLogPath"
}

if ($summary.result -ne "passed") {
    exit 1
}
exit 0
