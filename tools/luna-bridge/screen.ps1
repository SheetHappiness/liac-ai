param([Parameter(Mandatory = $true)][ValidatePattern('^[1-9][0-9]*$')][string]$Display)

$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms, System.Drawing
Add-Type @'
using System;
using System.Runtime.InteropServices;
public static class ScreenDpi {
    [DllImport("user32.dll")]
    public static extern IntPtr SetThreadDpiAwarenessContext(IntPtr context);
}
'@

$previousDpi = [ScreenDpi]::SetThreadDpiAwarenessContext([IntPtr](-4))
if ($previousDpi -eq [IntPtr]::Zero) { throw 'Could not select physical screen coordinates.' }
try {
    $screen = [System.Windows.Forms.Screen]::AllScreens |
        Where-Object DeviceName -eq "\\.\DISPLAY$Display"
    if (-not $screen) { throw 'Selected display is unavailable.' }
    $bounds = $screen.Bounds
    $size = $bounds.Size
    $bitmap = [System.Drawing.Bitmap]::new($size.Width, $size.Height)
    try {
        $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
        try {
            $graphics.CopyFromScreen($bounds.Location, [System.Drawing.Point]::Empty, $size)
        } finally {
            $graphics.Dispose()
        }
        $scale = [Math]::Min(1.0, 1280.0 / [Math]::Max($size.Width, $size.Height))
        $width = [Math]::Max(1, [int]($size.Width * $scale))
        $height = [Math]::Max(1, [int]($size.Height * $scale))
        $frame = [System.Drawing.Bitmap]::new($bitmap, $width, $height)
        try {
            $jpeg = [System.IO.MemoryStream]::new()
            try {
                $frame.Save($jpeg, [System.Drawing.Imaging.ImageFormat]::Jpeg)
                $jpeg.WriteTo([Console]::OpenStandardOutput())
            } finally {
                $jpeg.Dispose()
            }
        } finally {
            $frame.Dispose()
        }
    } finally {
        $bitmap.Dispose()
    }
} finally {
    $null = [ScreenDpi]::SetThreadDpiAwarenessContext($previousDpi)
}
