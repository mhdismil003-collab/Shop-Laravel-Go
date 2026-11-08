$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
. "$PSScriptRoot/scripts/Shop-Python.ps1"
Invoke-ShopPython -ShopArguments @('tests/shop_demo.py', 'stop')
