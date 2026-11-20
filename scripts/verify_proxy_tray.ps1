$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$exe = Join-Path $root 'CalamusProxyClient.exe'
Add-Type -AssemblyName PresentationFramework, System.Windows.Forms
$assembly = [Reflection.Assembly]::LoadFrom($exe)
$type = $assembly.GetType('CalamusProxyClient.MainWindow', $true)
$private = [Reflection.BindingFlags]'Instance,NonPublic'
$app = New-Object Windows.Application
$window = [Activator]::CreateInstance($type, [object[]]@($true, $false))
$app.MainWindow = $window
$closed = @{ Value = $false }
$window.add_Closed({ $closed.Value = $true })
$type.GetMethod('Start', $private).Invoke($window, @())
$menu = $type.GetField('trayMenu', $private).GetValue($window)
$tray = $type.GetField('tray', $private).GetValue($window)
if ($window.IsVisible -or $window.ShowInTaskbar -or !$tray.Visible) { throw 'Background startup must show only the tray icon' }
$menu.Items[0].PerformClick()
if (!$window.IsVisible -or !$window.ShowInTaskbar) { throw 'Opening from the tray must restore the window and taskbar entry' }
$window.WindowState = 'Maximized'
$window.WindowState = 'Minimized'
if (!$window.ShowInTaskbar -or !$window.IsVisible) { throw 'Minimize must keep the taskbar entry' }
$menu.Items[0].PerformClick()
if ($window.WindowState.ToString() -ne 'Maximized') { throw 'Restore must preserve the previous window state' }
$window.Close()
if ($closed.Value -or $window.IsVisible -or $window.ShowInTaskbar -or !$tray.Visible) { throw 'Close must hide the window while the app stays in the tray' }
$menu.Items[0].PerformClick()
if (!$window.IsVisible -or !$window.ShowInTaskbar) { throw 'Close-to-tray window did not reopen' }
$window.Close()
$menu.Items[$menu.Items.Count - 1].PerformClick()
if (!$closed.Value -or $null -ne $type.GetField('tray', $private).GetValue($window)) { throw 'Explicit exit must close the window and dispose the tray icon' }
Write-Host 'Tray startup, taskbar minimize, maximize restore, close-to-tray and full exit passed'

Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class TraySmokeNative {
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern IntPtr FindWindow(string className, string name);
    public static IntPtr FindProxyWindow() { return FindWindow(null, "Calamus ProxyClient"); }
    [DllImport("user32.dll")]
    public static extern bool IsWindowVisible(IntPtr window);
    [DllImport("user32.dll")]
    public static extern bool ShowWindow(IntPtr window, int action);
    [DllImport("user32.dll")]
    public static extern bool PostMessage(IntPtr window, uint message, IntPtr wParam, IntPtr lParam);
    [DllImport("user32.dll")]
    public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
}
'@
function Wait-Until($check, $message) {
    $timer = [Diagnostics.Stopwatch]::StartNew()
    while ($timer.Elapsed.TotalSeconds -lt 12) {
        if (& $check) { return }
        Start-Sleep -Milliseconds 100
    }
    throw $message
}
$process = Start-Process -FilePath $exe -ArgumentList '--background' -WorkingDirectory $root -PassThru
try {
    Wait-Until {
        if ($process.HasExited) { throw "Background process exited with code $($process.ExitCode)" }
        [TraySmokeNative]::FindProxyWindow() -ne [IntPtr]::Zero
    } 'Background process window was not initialized'
    $handle = [TraySmokeNative]::FindProxyWindow()
    if ([TraySmokeNative]::IsWindowVisible($handle)) { throw 'Background process unexpectedly became visible' }
    $second = Start-Process -FilePath $exe -WorkingDirectory $root -PassThru
    Wait-Until { [TraySmokeNative]::IsWindowVisible($handle) -and $second.HasExited } 'Relaunch failed to reveal the existing process'
    [uint32]$owner = 0
    [void][TraySmokeNative]::GetWindowThreadProcessId($handle, [ref]$owner)
    if ($owner -ne $process.Id -or $process.HasExited) { throw 'Relaunch replaced the running instance' }
    [void][TraySmokeNative]::PostMessage($handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    Wait-Until { ![TraySmokeNative]::IsWindowVisible($handle) } 'Close did not send the running process to the tray'
    [void][TraySmokeNative]::ShowWindow($handle, 5)
    Wait-Until { $process.Refresh(); [TraySmokeNative]::IsWindowVisible($handle) -and $process.MainWindowHandle -eq $handle } 'Launcher-style restore did not reveal the window'
    Start-Sleep -Milliseconds 200
    [void][TraySmokeNative]::PostMessage($handle, 0x0010, [IntPtr]::Zero, [IntPtr]::Zero)
    Wait-Until { ![TraySmokeNative]::IsWindowVisible($handle) } 'Closing after launcher-style restore did not return to tray'
    Write-Host 'Second launch and launcher-style window reveal passed'
} catch {
    $log = Join-Path $env:LOCALAPPDATA 'CalamusProxyClient/ui-startup-error.log'
    if (Test-Path -LiteralPath $log) { Get-Content -LiteralPath $log -Tail 30 }
    throw
} finally {
    if (!$process.HasExited) { Stop-Process -Id $process.Id }
    if ($null -ne $second -and !$second.HasExited) { Stop-Process -Id $second.Id }
}
