# Resolve Python without installing packages or changing the user's PATH.
$ErrorActionPreference = 'Stop'
$taskPython = $null
foreach ($taskName in @('python', 'python3')) {
    $taskCommand = Get-Command $taskName -ErrorAction SilentlyContinue
    if ($taskCommand -and $taskCommand.Source -notmatch 'WindowsApps') {
        $taskPython = $taskCommand.Source
        break
    }
}
if (-not $taskPython) {
    $taskAncestor = [System.IO.DirectoryInfo]$PSScriptRoot
    while ($taskAncestor) {
        $taskCandidate = Join-Path $taskAncestor.FullName '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
        if (Test-Path -LiteralPath $taskCandidate) {
            $taskPython = $taskCandidate
            break
        }
        $taskAncestor = $taskAncestor.Parent
    }
}
if (-not $taskPython) { throw 'Python 3.10+ is required. Use the Codex workspace runtime or install Python.' }
$taskScript = 'corpus.py'
if ($args.Count -gt 0 -and $args[0] -eq 'role') { $taskScript = 'harness.py' }
& $taskPython (Join-Path $PSScriptRoot $taskScript) @args
exit $LASTEXITCODE
