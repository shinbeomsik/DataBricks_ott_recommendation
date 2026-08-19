# OTT 추천 앱을 검증하고 Databricks에 배포한 뒤 실행하는 표준 진입 스크립트다.
# 중간 단계에서 오류가 나면 즉시 중단되므로 잘못된 구성을 실행 단계까지 넘기지 않는다.
[CmdletBinding()]
param(
    # ~/.databrickscfg에서 사용할 인증 프로필 이름이다.
    # 사용자가 별도 값을 주지 않으면 프로젝트 기본값인 DEFAULT를 사용한다.
    [ValidateNotNullOrEmpty()]
    [string] $Profile = "DEFAULT",

    # 배포 대상 환경을 허용된 값으로 제한해 오타로 엉뚱한 타겟을 만들지 않게 한다.
    [ValidateSet("dev", "staging", "prod")]
    [string] $Target = "dev"
)

# 외부 CLI나 검증 스크립트가 실패하면 이후 배포/실행을 계속하지 않는다.
$ErrorActionPreference = "Stop"

# 모든 경로를 현재 스크립트 위치 기준으로 계산하므로 어느 폴더에서 호출해도 동일하게 동작한다.
$cli = Join-Path $PSScriptRoot "databricks.ps1"
$check = Join-Path $PSScriptRoot "check.ps1"
$bundleRoot = Split-Path $PSScriptRoot -Parent

# 1) 사용 가능한 인증 프로필을 확인한다.
# 2) 선택한 프로필의 인증·CLI 버전·Bundle 기본 상태를 사전 점검한다.
& $cli auth profiles
& $check -Profile $Profile

# bundle 명령은 databricks.yml이 있는 프로젝트 루트에서 실행해야 한다.
Push-Location $bundleRoot
try {
    # strict 검증은 경고도 오류로 처리해 배포 전에 구성 문제를 발견한다.
    & $cli bundle validate --strict --target $Target --profile $Profile

    # 검증된 소스와 App 리소스 정의를 Workspace에 반영한다.
    & $cli bundle deploy --target $Target --profile $Profile

    # Bundle 배포만으로 앱 프로세스가 시작되지 않을 수 있으므로 App 리소스를 명시적으로 실행한다.
    & $cli bundle run ott_recommendation_app --target $Target --profile $Profile
}
finally {
    # 성공/실패와 관계없이 호출 전 작업 폴더로 복귀한다.
    Pop-Location
}
