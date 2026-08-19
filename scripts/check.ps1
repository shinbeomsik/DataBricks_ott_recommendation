[CmdletBinding()]
param(
    [ValidateNotNullOrEmpty()]
    [string] $Profile = "DEFAULT"
)

$ErrorActionPreference = "Stop"
$cli = Join-Path $PSScriptRoot "databricks.ps1"
$bundleRoot = Split-Path $PSScriptRoot -Parent
$previousProfile = $env:DATABRICKS_CONFIG_PROFILE

try {
    $env:DATABRICKS_CONFIG_PROFILE = $Profile
    Push-Location $bundleRoot
    try {
        & $cli version
        & $cli current-user me
        & $cli bundle validate
    }
    finally {
        Pop-Location
    }
}
finally {
    $env:DATABRICKS_CONFIG_PROFILE = $previousProfile
}

Write-Host "CLI, authentication, and bundle validation succeeded." -ForegroundColor Green
