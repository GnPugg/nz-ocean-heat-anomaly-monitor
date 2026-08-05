[CmdletBinding()]
param(
    [ValidateRange(30, 600)]
    [int]$HealthTimeoutSeconds = 120
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$ProjectRoot = Resolve-Path (
    Join-Path $PSScriptRoot "..\.."
)

function Assert-CommandExists {
    param(
        [Parameter(Mandatory)]
        [string]$CommandName
    )

    if (-not (Get-Command $CommandName -ErrorAction SilentlyContinue)) {
        throw "Required command is not available: $CommandName"
    }
}

function Invoke-NativeStep {
    param(
        [Parameter(Mandatory)]
        [string]$Name,

        [Parameter(Mandatory)]
        [scriptblock]$Command
    )

    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan

    & $Command
    $ExitCode = $LASTEXITCODE

    if ($ExitCode -ne 0) {
        throw "$Name failed with exit code $ExitCode."
    }
}

function Wait-ForPostgresHealth {
    param(
        [Parameter(Mandatory)]
        [int]$TimeoutSeconds
    )

    Write-Host ""
    Write-Host "=== Waiting for PostgreSQL health ===" -ForegroundColor Cyan

    $ContainerId = (
        & docker compose ps -q postgres
    ).Trim()

    if ($LASTEXITCODE -ne 0) {
        throw "Could not identify the PostgreSQL container."
    }

    if ([string]::IsNullOrWhiteSpace($ContainerId)) {
        throw "The PostgreSQL container was not created."
    }

    $Deadline = (Get-Date).AddSeconds($TimeoutSeconds)

    while ((Get-Date) -lt $Deadline) {
        $HealthStatus = (
            & docker inspect `
                --format "{{if .State.Health}}{{.State.Health.Status}}{{else}}missing{{end}}" `
                $ContainerId
        ).Trim()

        if ($LASTEXITCODE -ne 0) {
            throw "Could not inspect PostgreSQL container health."
        }

        switch ($HealthStatus) {
            "healthy" {
                Write-Host "PostgreSQL is healthy." -ForegroundColor Green
                return
            }

            "unhealthy" {
                throw "PostgreSQL reported an unhealthy status."
            }

            "missing" {
                throw "The PostgreSQL container has no configured health check."
            }

            default {
                Write-Host "PostgreSQL status: $HealthStatus"
                Start-Sleep -Seconds 2
            }
        }
    }

    throw (
        "PostgreSQL did not become healthy within " +
        "$TimeoutSeconds seconds."
    )
}

Assert-CommandExists -CommandName "docker"
Assert-CommandExists -CommandName "python"

$OriginalPythonPath = $env:PYTHONPATH

try {
    Push-Location $ProjectRoot

    if ([string]::IsNullOrWhiteSpace($OriginalPythonPath)) {
        $env:PYTHONPATH = $ProjectRoot.Path
    }
    else {
        $env:PYTHONPATH = (
            $ProjectRoot.Path +
            [IO.Path]::PathSeparator +
            $OriginalPythonPath
        )
    }

    Invoke-NativeStep `
        -Name "Checking Docker Compose" `
        -Command {
            docker compose version
        }

    Invoke-NativeStep `
        -Name "Checking Python project imports" `
        -Command {
            python -c "import nzheat; print('nzheat import successful')"
        }

    Invoke-NativeStep `
        -Name "Starting PostgreSQL" `
        -Command {
            docker compose up -d postgres
        }

    Wait-ForPostgresHealth `
        -TimeoutSeconds $HealthTimeoutSeconds

    Invoke-NativeStep `
        -Name "Validating processed outputs" `
        -Command {
            python .\scripts\maintenance\validate_outputs.py
        }

    Invoke-NativeStep `
        -Name "Publishing regional tables" `
        -Command {
            python -m nzheat.load.publish_all_postgres
        }

    Invoke-NativeStep `
        -Name "Publishing 686-cell analysis" `
        -Command {
            python -m nzheat.load.publish_cell_analysis_postgres
        }

    Invoke-NativeStep `
        -Name "Loading 10-year projection" `
        -Command {
            python -m nzheat.load.load_projection_10yr_to_postgres `
                --if-exists replace
        }

    Invoke-NativeStep `
        -Name "Verifying final database row counts" `
        -Command {
            python .\scripts\maintenance\verify_database_counts.py
        }

    Write-Host ""
    Write-Host "==============================================" `
        -ForegroundColor Green
    Write-Host "LOCAL DATABASE SETUP COMPLETED SUCCESSFULLY" `
        -ForegroundColor Green
    Write-Host "PostgreSQL: localhost:5433" `
        -ForegroundColor Green
    Write-Host "Database:   nzheat" `
        -ForegroundColor Green
    Write-Host "==============================================" `
        -ForegroundColor Green
}
finally {
    $env:PYTHONPATH = $OriginalPythonPath

    if ((Get-Location).Path -eq $ProjectRoot.Path) {
        Pop-Location
    }
}
