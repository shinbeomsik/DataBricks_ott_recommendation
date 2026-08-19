[CmdletBinding()]
param(
    [Parameter(Position = 0, ValueFromRemainingArguments = $true)]
    [string[]] $CliArguments
)

$ErrorActionPreference = "Stop"

$installedCommand = Get-Command databricks -ErrorAction SilentlyContinue
if ($null -ne $installedCommand) {
    $cliPath = $installedCommand.Source
}
else {
    $packageRoot = Join-Path $env:LOCALAPPDATA "Microsoft\WinGet\Packages"
    $cliPath = Get-ChildItem -LiteralPath $packageRoot -Directory -Filter "Databricks.DatabricksCLI_*" -ErrorAction SilentlyContinue |
        ForEach-Object {
            Get-ChildItem -LiteralPath $_.FullName -File -Filter "databricks.exe" -Recurse -ErrorAction SilentlyContinue
        } |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1 -ExpandProperty FullName
}

if ([string]::IsNullOrWhiteSpace($cliPath)) {
    throw "Databricks CLI was not found. Install it with: winget install --exact --id Databricks.DatabricksCLI --source winget"
}

& $cliPath @CliArguments
if ($LASTEXITCODE -ne 0) {
    throw "Databricks CLI exited with code $LASTEXITCODE."
}
