[CmdletBinding()]
param(
    [ValidatePattern("^https://")]
    [string] $WorkspaceHost = "",

    [ValidateNotNullOrEmpty()]
    [string] $Profile = "DEFAULT",

    [switch] $ConfigureServerless
)

$ErrorActionPreference = "Stop"
$cli = Join-Path $PSScriptRoot "databricks.ps1"

$loginArguments = @("auth", "login", "--profile", $Profile)
if (-not [string]::IsNullOrWhiteSpace($WorkspaceHost)) {
    $loginArguments += @("--host", $WorkspaceHost)
}
if ($ConfigureServerless -and -not [string]::IsNullOrWhiteSpace($WorkspaceHost)) {
    $loginArguments += "--configure-serverless"
}
elseif ($ConfigureServerless) {
    Write-Warning "-ConfigureServerless requires -WorkspaceHost and will be skipped. Bundle Jobs still select serverless compute from their resource configuration."
}

& $cli @loginArguments
& $cli current-user me --profile $Profile

Write-Host "Authentication profile '$Profile' is ready." -ForegroundColor Green
