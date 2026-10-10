param([Parameter(Mandatory=$true)][string]$Manifest)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type @'
using System;using System.Text;using System.Runtime.InteropServices;
public class HalfLightCookingWindow {
 [StructLayout(LayoutKind.Sequential)] public struct POINT {public int X,Y;}
 [DllImport("user32.dll")] public static extern bool ScreenToClient(IntPtr h,ref POINT p);
 [DllImport("user32.dll")] public static extern IntPtr SendMessage(IntPtr h,uint m,IntPtr w,IntPtr l);
 public delegate bool Callback(IntPtr h,IntPtr l);
 [DllImport("user32.dll")] public static extern bool EnumWindows(Callback c,IntPtr l);
 [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr h,out uint p);
 [DllImport("user32.dll",CharSet=CharSet.Unicode)] public static extern int GetWindowText(IntPtr h,StringBuilder b,int n);
 [DllImport("user32.dll")] public static extern bool ShowWindow(IntPtr h,int mode);
 public static void Show(uint target){EnumWindows((h,l)=>{uint p;GetWindowThreadProcessId(h,out p);var b=new StringBuilder(500);GetWindowText(h,b,500);if(p==target&&(b.ToString().StartsWith("C-Engine Editor")||b.ToString()=="Dying Light 2 - Developer Tools"))ShowWindow(h,4);return true;},IntPtr.Zero);}
}
'@
$job=Get-Content -LiteralPath $Manifest -Raw -Encoding UTF8 | ConvertFrom-Json
if($job.directory -notmatch '^HalfLightSetup(?:[a-f0-9]{12})?$'){throw 'Invalid setup project directory'}
$project=Join-Path $job.devtools ('projects/local/'+$job.directory)
function File-Hash($path){$stream=[IO.File]::OpenRead($path);$sha=[Security.Cryptography.SHA256]::Create();try{return [BitConverter]::ToString($sha.ComputeHash($stream)).Replace('-','').ToLowerInvariant()}finally{$stream.Dispose();$sha.Dispose()}}
$existing=@(Get-Process -Name Editor_DevTools_x64_rwe -ErrorAction SilentlyContinue)
$needsOpen=$true
$startedEditor=$false
if($existing.Count -gt 1){throw 'Close additional Developer Tools windows before cooking'}
if($existing.Count -eq 1){
    $editor=$existing[0]
    if($editor.MainWindowTitle -like ('* : '+$job.name)){$needsOpen=$false}
    elseif($editor.MainWindowTitle -ne 'Dying Light 2 - Developer Tools'){throw 'A different editor project is open; preserving it'}
} else {
    $editor=Start-Process -FilePath (Join-Path $job.devtools 'bin/Editor_DevTools_x64_rwe.exe') -WorkingDirectory (Join-Path $job.devtools 'bin') -WindowStyle Hidden -PassThru
    $startedEditor=$true
}
$condition=New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ProcessIdProperty,$editor.Id)
function Windows { return [System.Windows.Automation.AutomationElement]::RootElement.FindAll([System.Windows.Automation.TreeScope]::Children,$condition) }
function Find-Control($name,$type) {
    $match=New-Object System.Windows.Automation.AndCondition((New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::NameProperty,$name)),(New-Object System.Windows.Automation.PropertyCondition([System.Windows.Automation.AutomationElement]::ControlTypeProperty,$type)))
    foreach($window in (Windows)){$found=$window.FindFirst([System.Windows.Automation.TreeScope]::Descendants,$match);if($found){return $found}}
    return $null
}
function Wait-Control($name,$type) {
    $deadline=[DateTime]::UtcNow.AddSeconds(180)
    do {
        $editor.Refresh();if($editor.HasExited){throw 'Developer Tools exited during cooking'}
        [HalfLightCookingWindow]::Show($editor.Id)
        $found=Find-Control $name $type;if($found){return $found}
        Start-Sleep -Milliseconds 250
    }while([DateTime]::UtcNow -lt $deadline)
    throw ('Developer Tools did not expose '+$name+'; no other window was controlled')
}
function Invoke-Control($name,$type) {
    $element=Wait-Control $name $type
    $element.GetCurrentPattern([System.Windows.Automation.InvokePattern]::Pattern).Invoke()
}
if($needsOpen){
    if(-not (Test-Path -LiteralPath $project)){
        Invoke-Control 'Create New Project...' ([System.Windows.Automation.ControlType]::Button)
        $field=Wait-Control 'Name:' ([System.Windows.Automation.ControlType]::Edit)
        $field.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($job.name)
        $field=Wait-Control 'Directory name:' ([System.Windows.Automation.ControlType]::Edit)
        $field.GetCurrentPattern([System.Windows.Automation.ValuePattern]::Pattern).SetValue($job.directory)
        $empty=Wait-Control 'empty' ([System.Windows.Automation.ControlType]::ListItem)
        $empty.GetCurrentPattern([System.Windows.Automation.SelectionItemPattern]::Pattern).Select()
        Invoke-Control 'OK' ([System.Windows.Automation.ControlType]::Button)
    } else {
        $entry=Wait-Control $job.name ([System.Windows.Automation.ControlType]::TreeItem)
        # Qt table cells expose Invoke but no selection pattern; select only this SDK row.
        $row=$entry.Current.BoundingRectangle;$point=New-Object HalfLightCookingWindow+POINT
        $point.X=[int]($row.X+$row.Width/2);$point.Y=[int]($row.Y+$row.Height/2)
        $window=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($entry)
        while($window -and $window.Current.NativeWindowHandle -eq 0){$window=[System.Windows.Automation.TreeWalker]::ControlViewWalker.GetParent($window)}
        if(-not $window -or $window.Current.ProcessId -ne $editor.Id){throw 'SDK selection window identity changed'}
        $hwnd=[IntPtr]$window.Current.NativeWindowHandle
        [void][HalfLightCookingWindow]::ScreenToClient($hwnd,[ref]$point)
        $xy=[IntPtr](($point.Y -shl 16) -bor ($point.X -band 65535))
        [void][HalfLightCookingWindow]::SendMessage($hwnd,513,[IntPtr]1,$xy)
        [void][HalfLightCookingWindow]::SendMessage($hwnd,514,[IntPtr]0,$xy)
        Invoke-Control 'Open Project' ([System.Windows.Automation.ControlType]::Button)
    }
}
[void](Wait-Control 'Models' ([System.Windows.Automation.ControlType]::Text))
if(-not (Test-Path -LiteralPath (Join-Path $project 'fs.ini'))){throw 'Setup project was not created'}
$sourceRoot=Join-Path $project 'source/data/Meshes'
[void][IO.Directory]::CreateDirectory($sourceRoot)
$sourceJournal=Join-Path (Split-Path -Parent $Manifest) 'cook-sources.json'
$owned=@{}
if(Test-Path -LiteralPath $sourceJournal){
    $prior=Get-Content -LiteralPath $sourceJournal -Raw | ConvertFrom-Json
    if($prior.project -ne $project){throw 'Cooking ownership belongs to a different project'}
    foreach($entry in $prior.files){$owned[$entry.name]=$entry.sha256}
}
foreach($item in $job.files){
    if($item.name -notmatch '^halflight_[a-z0-9_]+\.(msh|skn)$'){throw 'Invalid generated mesh name'}
    if((File-Hash $item.source) -ne $item.sha256){throw 'Generated source changed'}
    $target=Join-Path $sourceRoot $item.name
    if(Test-Path -LiteralPath $target){
        $current=File-Hash $target
        if($current -ne $item.sha256){
            if($owned[$item.name] -ne $current){throw ('Preserving differing source '+$item.name)}
            Copy-Item -LiteralPath $item.source -Destination $target -Force
        }
    }else{Copy-Item -LiteralPath $item.source -Destination $target}
    $owned[$item.name]=$item.sha256
    $record=@{project=$project;files=@($owned.GetEnumerator() | ForEach-Object {@{name=$_.Key;sha256=$_.Value}})}
    $record | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath ($sourceJournal+'.tmp') -Encoding UTF8
    Move-Item -LiteralPath ($sourceJournal+'.tmp') -Destination $sourceJournal -Force
}
Invoke-Control 'Models' ([System.Windows.Automation.ControlType]::Text)
$compiledRoot=Join-Path $project 'work/data_platform/pc/assets/meshes'
$deadline=[DateTime]::UtcNow.AddSeconds(300)
do {
    $ready=0
    foreach($item in $job.files | Where-Object name -Like '*.msh'){
        $compiled=Join-Path $compiledRoot ($item.name+'_obj')
        $dependency=$compiled+'_dep'
        if((Test-Path -LiteralPath $compiled) -and (Test-Path -LiteralPath $dependency)){
            $source=Get-Item -LiteralPath (Join-Path $sourceRoot $item.name)
            if((Get-Item -LiteralPath $compiled).Length -gt 0 -and (Get-Item -LiteralPath $compiled).LastWriteTimeUtc -ge $source.LastWriteTimeUtc){$ready++}
        }
    }
    Write-Output ('Cooked '+$ready+' / '+@($job.files | Where-Object name -Like '*.msh').Count)
    if($ready -eq @($job.files | Where-Object name -Like '*.msh').Count){
        Write-Output 'Official cooking complete'
        if(-not $startedEditor){exit 0}
        $editor.Refresh()
        if($editor.MainWindowTitle -notlike ('* : '+$job.name)){throw 'SDK project changed before shutdown'}
        [void]$editor.CloseMainWindow()
        if(-not $editor.WaitForExit(15000)){
            $editor.Refresh()
            if($editor.HasExited){exit 0}
            if($editor.MainWindowTitle -notlike ('* : '+$job.name) -and $editor.MainWindowTitle -notin @('','C-Engine Editor','Dying Light 2 - Developer Tools')){throw 'SDK identity changed during shutdown'}
            if($editor.Path -ne (Join-Path $job.devtools 'bin/Editor_DevTools_x64_rwe.exe')){throw 'SDK executable identity changed'}
            # This disposable setup project has finished compiling; release its render resources.
            Stop-Process -Id $editor.Id
            if(-not $editor.WaitForExit(5000)){throw 'Setup editor did not exit after cooking'}
        }
        exit 0
    }
    $editor.Refresh();if($editor.HasExited){throw 'Developer Tools exited before all meshes cooked'}
    Start-Sleep -Seconds 2
}while([DateTime]::UtcNow -lt $deadline)
throw 'Cooking did not finish; generated assets remain private and setup is not marked ready'
