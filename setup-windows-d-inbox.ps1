$ErrorActionPreference = "Stop"

$Folder = "D:\\HosseinHub-Inbox"
$ShareName = "HosseinHub-Inbox"

New-Item -ItemType Directory -Path $Folder -Force | Out-Null

$existing = Get-SmbShare -Name $ShareName -ErrorAction SilentlyContinue
if ($existing) {
    Set-SmbShare -Name $ShareName -FolderEnumerationMode AccessBased -CachingMode None -Force
} else {
    New-SmbShare -Name $ShareName -Path $Folder -FullAccess "$env:COMPUTERNAME\\$env:USERNAME" -FolderEnumerationMode AccessBased -CachingMode None
}

$acl = Get-Acl $Folder
$rule = New-Object System.Security.AccessControl.FileSystemAccessRule("$env:COMPUTERNAME\\$env:USERNAME","FullControl","ContainerInherit,ObjectInherit","None","Allow")
$acl.SetAccessRule($rule)
Set-Acl -Path $Folder -AclObject $acl

Write-Host ""
Write-Host "WINDOWS INBOX READY"
Write-Host "Folder: $Folder"
Write-Host "Share: \\$env:COMPUTERNAME\\$ShareName"
Write-Host ""
Write-Host "Put PDFs/images into this folder. Hossein Hub will read them over SMB."
