param([switch]$PrepareOnly, [string]$Prepared = '')
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. "$PSScriptRoot/scripts/Shop-Python.ps1"
$shopArgs = @('tests/shop_demo.py', 'race')
if ($PrepareOnly) { $shopArgs += '--prepare-only' }
if ($Prepared) { $shopArgs += @('--prepared', $Prepared) }
Invoke-ShopPython -ShopArguments $shopArgs
