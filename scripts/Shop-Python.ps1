function Invoke-ShopPython {
    param([string[]]$ShopArguments)
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3 -X utf8 -u @ShopArguments
    } elseif (Get-Command python -ErrorAction SilentlyContinue) {
        & python -X utf8 -u @ShopArguments
    } else {
        throw 'Install Python 3.10 or later, then run this command again.'
    }
    if ($LASTEXITCODE -ne 0) {
        throw 'Shop command failed. Read the error printed above.'
    }
}
