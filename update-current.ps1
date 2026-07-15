$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "update-current.py"
if (Get-Command py -ErrorAction SilentlyContinue) {
  & py -3 $script @args
} elseif (Get-Command python -ErrorAction SilentlyContinue) {
  & python $script @args
} else {
  Write-Error "Python 3 is required. Install Python, then run this command again."
}
exit $LASTEXITCODE
