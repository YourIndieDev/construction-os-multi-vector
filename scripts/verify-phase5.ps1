[CmdletBinding()]
param(
    [string]$ProjectId = "",
    [string]$ProjectName = "Test",
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

function Has-Property {
    param($Object, [string]$Name)
    return $null -ne $Object -and $Object.PSObject.Properties.Name -contains $Name
}

function Get-PropertyValue {
    param($Object, [string]$Name, $Default = $null)
    if (Has-Property $Object $Name) { return $Object.$Name }
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
            $qdrant = Get-PropertyValue $health "qdrant"
            $colsmol = Get-PropertyValue $health "colsmol"
            if ($null -ne $qdrant -and $null -ne $colsmol -and
                [bool](Get-PropertyValue $qdrant "available" $false) -and
                [bool](Get-PropertyValue $colsmol "available" $false)) {
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

function Get-SourceStatus {
    param([string]$Pid, [string]$Sid)

    $p = [uri]::EscapeDataString($Pid)
    $s = [uri]::EscapeDataString($Sid)
    return Invoke-Api -Method GET -Path ("/api/drawing-extractions/multivector/projects/{0}/sources/{1}" -f $p, $s)
}

function Invoke-SourceAction {
    param([string]$Pid, [string]$Sid, [string]$Action)

    $p = [uri]::EscapeDataString($Pid)
    $s = [uri]::EscapeDataString($Sid)
    return Invoke-Api -Method POST -Path ("/api/drawing-extractions/multivector/projects/{0}/sources/{1}/{2}" -f $p, $s, $Action)
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

        if ($status -eq "ready" -and $points -gt 0) { return $last }
        if ($status -eq "error") {
            $detail = [string](Get-PropertyValue $last "last_error" "Unknown indexing error")
            throw ("{0} failed: {1}" -f $Label, $detail)
        }
        Start-Sleep -Seconds 5
    }

    $lastJson = $last | ConvertTo-Json -Depth 8 -Compress
    throw ("{0} timed out after {1} minutes. Last state: {2}" -f $Label, $TimeoutMinutes, $lastJson)
}

function Get-Projects {
    $response = Invoke-Api -Method GET -Path "/api/projects?archived=false&order_by=updated%20desc"
    if (Has-Property $response "projects") { return @($response.projects) }
    if (Has-Property $response "results") { return @($response.results) }
    return @($response)
}

function Get-ProjectPdfSources {
    param([string]$Pid)

    $p = [uri]::EscapeDataString($Pid)
    $response = Invoke-Api -Method GET -Path ("/api/sources?project_id={0}&limit=100&offset=0&sort_by=updated&sort_order=desc" -f $p)
    $sources = if (Has-Property $response "sources") { @($response.sources) } elseif (Has-Property $response "results") { @($response.results) } else { @($response) }
    $pdfs = @()

    foreach ($source in $sources) {
        $sourceId = [string](Get-PropertyValue $source "id" "")
        $title = [string](Get-PropertyValue $source "title" "")
        $asset = Get-PropertyValue $source "asset"
        $filePath = if ($null -ne $asset) { [string](Get-PropertyValue $asset "file_path" "") } else { "" }
        $isPdf = $filePath.EndsWith(".pdf", [System.StringComparison]::OrdinalIgnoreCase) -or
                 $title.EndsWith(".pdf", [System.StringComparison]::OrdinalIgnoreCase)

        Write-Host ("Source {0}: title='{1}', file='{2}', pdf={3}" -f $sourceId, $title, $filePath, $isPdf)

        if (-not [string]::IsNullOrWhiteSpace($sourceId) -and $isPdf) {
            $pdfs += [pscustomobject]@{
                source_id = $sourceId
                source_title = $title
                file_path = $filePath
            }
        }
    }

    return @($pdfs)
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
        Invoke-Native -FilePath "docker" -Arguments @("compose", "build", "construction_os", "colsmol")
        $summary.checks["build"] = "passed"
    }
    else {
        $summary.checks["build"] = "skipped"
    }

    Write-Step "Start isolated stack"
    Invoke-Native -FilePath "docker" -Arguments @("compose", "up", "-d", "qdrant", "colsmol", "construction_os")
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
    Invoke-Native -FilePath "docker" -Arguments @("compose", "exec", "-T", "colsmol", "pytest", "-q", "tests/test_contract.py")
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
        Invoke-Native -FilePath "docker" -Arguments @("build", "--target", "builder", "-t", "construction-os-multivector-test", ".")
        Invoke-Native -FilePath "docker" -Arguments @(
            "run", "--rm", "construction-os-multivector-test", "sh", "-lc",
            "cd /app/frontend && npm test -- src/components/multivector/ProjectMultiVectorDialog.test.tsx"
        )
        $summary.checks["frontend_tests"] = "passed"
    }
    else {
        $summary.checks["frontend_tests"] = "skipped"
    }

    Write-Step "Select the Test project PDF"
    $projects = @(Get-Projects)
    $selectedProject = $null
    $pdfSources = @()

    if (-not [string]::IsNullOrWhiteSpace($ProjectId)) {
        $selectedProject = $projects | Where-Object { [string](Get-PropertyValue $_ "id" "") -eq $ProjectId } | Select-Object -First 1
        if ($null -eq $selectedProject) { throw ("Project '{0}' was not returned by the projects API." -f $ProjectId) }
        $pdfSources = @(Get-ProjectPdfSources -Pid $ProjectId)
    }
    else {
        $orderedProjects = @($projects | Sort-Object @{ Expression = { if ([string](Get-PropertyValue $_ "name" "") -eq $ProjectName) { 0 } else { 1 } } }, @{ Expression = { [string](Get-PropertyValue $_ "name" "") } })
        foreach ($project in $orderedProjects) {
            $candidateId = [string](Get-PropertyValue $project "id" "")
            $candidateName = [string](Get-PropertyValue $project "name" $candidateId)
            if ([string]::IsNullOrWhiteSpace($candidateId)) { continue }

            Write-Host ("Checking project '{0}' [{1}]" -f $candidateName, $candidateId)
            try {
                $candidatePdfs = @(Get-ProjectPdfSources -Pid $candidateId)
                if ($candidatePdfs.Count -gt 0) {
                    $selectedProject = $project
                    $pdfSources = $candidatePdfs
                    break
                }
            }
            catch {
                Write-Warning ("Could not inspect project '{0}': {1}" -f $candidateName, $_.Exception.Message)
            }
        }
    }

    if ($null -eq $selectedProject -or $pdfSources.Count -eq 0) {
        throw ("No PDF source was returned for project '{0}'. Review the source lines printed above." -f $ProjectName)
    }

    $selectedProjectId = [string](Get-PropertyValue $selectedProject "id" "")
    $selectedProjectName = [string](Get-PropertyValue $selectedProject "name" $selectedProjectId)
    $summary.project_id = $selectedProjectId
    $summary.project_name = $selectedProjectName
    Write-Host ("Selected project: {0} [{1}]" -f $selectedProjectName, $selectedProjectId)
    Write-Host ("PDF sources: {0}" -f $pdfSources.Count)

    $primary = $pdfSources[0]
    $primaryId = [string]$primary.source_id
    $primaryTitle = [string]$primary.source_title
    $summary.primary_source = [ordered]@{ id = $primaryId; title = $primaryTitle; file_path = [string]$primary.file_path }

    Write-Step "Index primary PDF using the same enable action as the UI icon"
    try {
        $queued = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "enable"
    }
    catch {
        throw ("The PDF was found, but indexing could not start. Source '{0}', stored file '{1}'. API error: {2}" -f $primaryTitle, $primary.file_path, $_.Exception.Message)
    }
    Write-Host ($queued | ConvertTo-Json -Depth 8)
    $ready = Wait-SourceReady -Pid $selectedProjectId -Sid $primaryId -Label "Primary enable"
    $summary.primary_source["first_ready_points"] = [int](Get-PropertyValue $ready "point_count" 0)
    $summary.checks["primary_enable"] = "passed"

    Write-Step "Disable primary PDF"
    $disabled = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "disable"
    if ([string](Get-PropertyValue $disabled "status" "") -ne "disabled" -or [bool](Get-PropertyValue $disabled "enabled" $true)) {
        throw ("Disable verification failed: {0}" -f ($disabled | ConvertTo-Json -Depth 8 -Compress))
    }
    $summary.checks["primary_disable"] = "passed"

    Write-Step "Re-enable primary PDF"
    $null = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "enable"
    $readyAgain = Wait-SourceReady -Pid $selectedProjectId -Sid $primaryId -Label "Primary re-enable"
    $summary.primary_source["reenabled_points"] = [int](Get-PropertyValue $readyAgain "point_count" 0)
    $summary.checks["primary_reenable"] = "passed"

    Write-Step "Clean rebuild primary PDF"
    $rebuild = Invoke-SourceAction -Pid $selectedProjectId -Sid $primaryId -Action "rebuild"
    Write-Host ($rebuild | ConvertTo-Json -Depth 8)
    $rebuilt = Wait-SourceReady -Pid $selectedProjectId -Sid $primaryId -Label "Primary rebuild"
    $summary.primary_source["rebuilt_points"] = [int](Get-PropertyValue $rebuilt "point_count" 0)
    $summary.checks["primary_rebuild"] = "passed"

    if ($pdfSources.Count -gt 1) {
        Write-Step "Index a second PDF independently"
        $secondary = $pdfSources[1]
        $secondaryId = [string]$secondary.source_id
        $secondaryTitle = [string]$secondary.source_title
        $summary.secondary_source = [ordered]@{ id = $secondaryId; title = $secondaryTitle; file_path = [string]$secondary.file_path }

        $null = Invoke-SourceAction -Pid $selectedProjectId -Sid $secondaryId -Action "enable"
        $secondaryReady = Wait-SourceReady -Pid $selectedProjectId -Sid $secondaryId -Label "Secondary enable"
        $primaryStillReady = Get-SourceStatus -Pid $selectedProjectId -Sid $primaryId

        if ([string](Get-PropertyValue $primaryStillReady "status" "") -ne "ready" -or [int](Get-PropertyValue $primaryStillReady "point_count" 0) -lt 1) {
            throw "Primary source was disturbed while indexing the secondary source."
        }

        $summary.secondary_source["ready_points"] = [int](Get-PropertyValue $secondaryReady "point_count" 0)
        $summary.checks["secondary_independence"] = "passed"
    }
    else {
        Write-Warning "Only one PDF exists in Test. Real second-source verification was skipped; automated two-source isolation coverage remains active."
        $summary.secondary_source = [ordered]@{
            result = "skipped"
            reason = "Only one PDF was available in Test"
            automated_coverage = "tests/test_multivector_indexer_isolation.py"
        }
        $summary.checks["secondary_independence"] = "covered_by_automated_test"
    }

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
        & docker compose logs --no-color --tail=400 construction_os colsmol qdrant | Out-File -FilePath $composeLogPath -Encoding utf8
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
