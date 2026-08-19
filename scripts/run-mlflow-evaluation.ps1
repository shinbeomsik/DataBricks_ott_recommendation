# MLflow Experiment와 평가 Job을 검증·배포한 뒤 즉시 한 번 실행하는 표준 스크립트다.
[CmdletBinding()]
param(
    # ~/.databrickscfg에서 사용할 인증 프로필이다.
    [ValidateNotNullOrEmpty()]
    [string] $Profile = "DEFAULT",

    # 현재 Bundle에 정의된 배포 대상 환경이다.
    [ValidateSet("dev", "staging", "prod")]
    [string] $Target = "dev"
)

$ErrorActionPreference = "Stop"
$cli = Join-Path $PSScriptRoot "databricks.ps1"
$check = Join-Path $PSScriptRoot "check.ps1"
$bundleRoot = Split-Path $PSScriptRoot -Parent

# Workspace 작업 전에 인증 프로필과 현재 사용자를 확인한다.
& $cli auth profiles
& $check -Profile $Profile

Push-Location $bundleRoot
try {
    # strict 검증 → 배포 → 실행 순서를 지켜 잘못된 Job이 실행되지 않게 한다.
    & $cli bundle validate --strict --target $Target --profile $Profile
    & $cli bundle deploy --target $Target --profile $Profile
    & $cli bundle run ott_recommendation_evaluation_job --target $Target --profile $Profile
}
finally {
    Pop-Location
}
