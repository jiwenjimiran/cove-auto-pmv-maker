param(
    [string]$InitialPath = '',
    [string]$Title = 'Choose a folder'
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName System.Windows.Forms

$dialog = New-Object System.Windows.Forms.FolderBrowserDialog
$dialog.Description = $Title
$dialog.ShowNewFolderButton = $true
if ($InitialPath -and [System.IO.Directory]::Exists($InitialPath)) {
    $dialog.SelectedPath = $InitialPath
}

try {
    if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK) {
        [Console]::WriteLine('PMV_PICKED:' + $dialog.SelectedPath)
    }
}
finally {
    $dialog.Dispose()
}
