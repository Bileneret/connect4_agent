param([string]$Text = "ZCode: сообщение")
$ErrorActionPreference = "Continue"
try {
    [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
    [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null
    $safe = $Text -replace '&', '&amp;' -replace '<', '&lt;' -replace '>', '&gt;'
    $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
    $xml.LoadXml("<toast><visual><binding template='ToastGeneric'><text>ZCode</text><text>$safe</text></binding></visual></toast>")
    $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
    [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("ZCode").Show($toast)
    Write-Output "toast shown"
} catch {
    Write-Output ("toast failed: " + $_.Exception.Message)
}
