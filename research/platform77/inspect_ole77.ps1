param(
    [Parameter(Mandatory = $true)]
    [string]$OutputPath
)

# Read-only prerequisite check. Does not launch 1C or register COM classes.
$ErrorActionPreference = 'Stop'
$progIds = @('V77.Application', 'V77L.Application', 'V77M.Application', 'V77S.Application', 'V1CEnterprise.Application')
$registry = foreach ($view in @([Microsoft.Win32.RegistryView]::Registry32, [Microsoft.Win32.RegistryView]::Registry64)) {
    $root = [Microsoft.Win32.RegistryKey]::OpenBaseKey([Microsoft.Win32.RegistryHive]::ClassesRoot, $view)
    try {
        foreach ($progId in $progIds) {
            $key = $root.OpenSubKey($progId)
            $clsidKey = $null
            $serverKey = $null
            try {
                $clsid = $null
                $server = $null
                if ($null -ne $key) {
                    $clsidKey = $key.OpenSubKey('CLSID')
                    if ($null -ne $clsidKey) { $clsid = $clsidKey.GetValue('') }
                    if ($clsid) { $serverKey = $root.OpenSubKey('CLSID\' + $clsid + '\LocalServer32') }
                    if ($null -ne $serverKey) { $server = $serverKey.GetValue('') }
                }
                [pscustomobject]@{ view = [string]$view; progid = $progId; present = ($null -ne $key); clsid = $clsid; local_server = $server }
            } finally {
                if ($null -ne $serverKey) { $serverKey.Dispose() }
                if ($null -ne $clsidKey) { $clsidKey.Dispose() }
                if ($null -ne $key) { $key.Dispose() }
            }
        }
    } finally { $root.Dispose() }
}

$resolution = foreach ($progId in $progIds) {
    try {
        $comType = [type]::GetTypeFromProgID($progId, $true)
        [pscustomobject]@{ progid = $progId; resolved = $true; clsid = [string]$comType.GUID }
    } catch {
        $failure = $_.Exception.GetBaseException()
        [pscustomobject]@{ progid = $progId; resolved = $false; hresult = ('0x{0:X8}' -f $failure.HResult); message = $failure.Message }
    }
}

$report = [ordered]@{
    schema_version = 1
    scope = 'ole_prerequisites_only'
    observed_at = (Get-Date).ToString('o')
    process_bits = [IntPtr]::Size * 8
    powershell_version = [string]$PSVersionTable.PSVersion
    registry = @($registry)
    progid_resolution = @($resolution)
    outcome = $(if (@($resolution | Where-Object { $_.resolved }).Count) { 'class_resolution_available' } else { 'blocked' })
    reason = $(if (@($resolution | Where-Object { $_.resolved }).Count) { $null } else { 'com_class_unavailable' })
    database_open_attempted = $false
    registry_changed = $false
}
$fullOutputPath = [IO.Path]::GetFullPath($OutputPath)
$json = $report | ConvertTo-Json -Depth 8
[IO.File]::WriteAllText($fullOutputPath, $json + [Environment]::NewLine, (New-Object System.Text.UTF8Encoding($false)))
$json
