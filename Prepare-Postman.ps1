param([switch]$NoBrowser)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. "$PSScriptRoot/scripts/Shop-Python.ps1"
$shopArgs = @('tests/shop_demo.py', 'prepare')
if ($NoBrowser) { $shopArgs += '--no-browser' }
Invoke-ShopPython -ShopArguments $shopArgs
