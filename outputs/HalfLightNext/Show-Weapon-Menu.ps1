param([int]$TargetPid=0,[ValidatePattern('^[0-9a-f]{16}$')][string]$Session='0000000000000000',[switch]$Check,[switch]$Retail)
$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
Add-Type -ReferencedAssemblies 'System.Windows.Forms' -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public class HalfLightMenuWindow : System.Windows.Forms.IWin32Window {
    public IntPtr Handle { get; set; }
    [DllImport("user32.dll")] public static extern short GetAsyncKeyState(int key);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr window, out uint pid);
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("kernel32.dll")] public static extern ulong GetTickCount64();
    [DllImport("user32.dll")] public static extern bool AttachThreadInput(uint from, uint to, bool attach);
    [DllImport("user32.dll")] public static extern bool SetForegroundWindow(IntPtr window);
    [DllImport("user32.dll")] public static extern IntPtr SetFocus(IntPtr window);
    [DllImport("user32.dll")] public static extern bool BringWindowToTop(IntPtr window);
    [DllImport("user32.dll")] public static extern bool ClipCursor(IntPtr rect);
    public static void FocusMenu(IntPtr window) {
        uint pid; uint foreground=GetWindowThreadProcessId(GetForegroundWindow(),out pid), current=GetCurrentThreadId();
        bool attached=foreground!=current && AttachThreadInput(current,foreground,true);
        try { BringWindowToTop(window);SetForegroundWindow(window);SetFocus(window);ClipCursor(IntPtr.Zero); }
        finally { if(attached)AttachThreadInput(current,foreground,false); }
    }
}
public class HalfLightMenuPreview : System.Windows.Forms.Form {
    protected override bool ShowWithoutActivation { get { return true; } }
}
'@
$taskRoot=Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
$lab=Join-Path $taskRoot 'work\lab'
$retailDir=Join-Path $taskRoot 'work\retail'
if($Retail -and $Check){$retailDir=Join-Path $lab 'campaign-menu-check';[void][IO.Directory]::CreateDirectory($retailDir)}
if($Retail -and -not $Check){
    $created=$false;$panelMutex=[Threading.Mutex]::new($false,'Local\HalfLightCampaignF7-20261010',[ref]$created)
    if(-not $created){$panelMutex.Dispose();exit 0}
}
$request=Join-Path $lab "weapon-menu-request-$Session.txt"
$statusPath=Join-Path $lab "weapon-menu-status-$Session.txt"
$sequence=[long]0;$lastF7=$false;$form=$null;$pending=[long]0
$script:menuLeaseDeadline=[uint64]0
function Update-CampaignMenu {
    try {$script:campaignStatus=Get-Content (Join-Path $retailDir 'panel-status.json') -Raw | ConvertFrom-Json} catch {$script:campaignStatus=$null}
    $fresh=$campaignStatus -and ([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$campaignStatus.updated_at -lt 3)
    if($Retail -and -not $Check -and $campaignStatus -and -not $fresh -and $campaignStatus.panel_pid -and -not (Get-Process -Id $campaignStatus.panel_pid -ErrorAction SilentlyContinue)){
        $script:workerLost=$true
        if($script:form){$script:form.Close()}
        return
    }
    if($fresh -and $campaignStatus.connected -and $campaignStatus.session -match '^[0-9a-f]{16}$'){
        if($script:Session -ne $campaignStatus.session){$script:pending=0;$script:sequence=0;$script:menuLeaseDeadline=0}
        $script:Session=$campaignStatus.session;$script:TargetPid=[int]$campaignStatus.target_pid
        $script:request=Join-Path $lab "weapon-menu-request-$Session.txt";$script:statusPath=Join-Path $lab "weapon-menu-status-$Session.txt"
    }else{
        $game=Get-Process -Name 'DyingLightGame_x64_rwdi' -ErrorAction SilentlyContinue | Select-Object -First 1
        $script:TargetPid=if($game){$game.Id}else{0};$script:menuLeaseDeadline=0
    }
    if($script:bridgeStatus){
        $bridgeStatus.Text=if($fresh){(($campaignStatus.rows | ForEach-Object {"$($_.part): $($_.state)"}) -join "`r`n")+"`r`n"+($campaignStatus.errors -join '; ')}else{'Status unavailable; panel worker is not responding.'}
        $bridgeStatus.ForeColor=if(-not $fresh -or $campaignStatus.errors.Count){[Drawing.Color]::Firebrick}else{[Drawing.Color]::Black}
        if(-not $script:pending){$apply.Enabled=$fresh -and $campaignStatus.connected -and (Menu-SessionAlive)}
        $busy=$fresh -and $campaignStatus.command.state -eq 'working'
        foreach($button in @($startBridge,$stopBridge,$restartBridge)){$button.Enabled=$fresh -and -not $busy}
        if($fresh -and $campaignStatus.command.sequence -eq $script:bridgeSequence){$message.Text=$campaignStatus.command.message}
    }
}
function Request-Bridge([string]$action){
    $script:bridgeSequence=[DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()*1000000
    $body=@{sequence=$bridgeSequence;action=$action;expires_at=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+30} | ConvertTo-Json
    $path=Join-Path $retailDir 'panel-request.json';[IO.File]::WriteAllText($path+'.tmp',$body)
    if(Test-Path -LiteralPath $path){[IO.File]::Replace($path+'.tmp',$path,[NullString]::Value)}else{[IO.File]::Move($path+'.tmp',$path)}
    $message.Text=$action+' requested...'
}
function Menu-Trace($event) {
    [IO.File]::AppendAllText((Join-Path $lab "weapon-menu-ui-$Session.log"),"$([DateTimeOffset]::UtcNow.ToUnixTimeMilliseconds()) $event`n")
}
function Menu-SessionAlive {
    $now=[HalfLightMenuWindow]::GetTickCount64()
    try {
        if((Test-Path -LiteralPath (Join-Path $lab "guest-stop-$Session.txt")) -or (Test-Path -LiteralPath (Join-Path $lab 'halflight-launcher-stop.txt'))){$script:menuLeaseDeadline=0;return $false}
        $active=Get-Content (Join-Path $lab 'active-axe-session.json') -Raw | ConvertFrom-Json
        $game=Get-Process -Id $TargetPid -ErrorAction Stop
        $expectedProcess=if($active.host -eq 'retail'){'DyingLightGame_x64_rwdi'}else{'DyingLightGame_x64_rwe'}
        if($active.session -ne $Session -or $active.target_pid -ne $TargetPid -or $active.state -notin @('starting','running') -or $game.ProcessName -ne $expectedProcess){$script:menuLeaseDeadline=0;return $false}
        $lease=[IO.File]::ReadAllBytes((Join-Path $lab "native-axe-session-$TargetPid.lease"));$now=[HalfLightMenuWindow]::GetTickCount64()
        $valid=$lease.Length -eq 24 -and [BitConverter]::ToUInt32($lease,0) -eq 0x31534648 -and [BitConverter]::ToUInt32($lease,4) -eq $TargetPid -and [BitConverter]::ToUInt64($lease,8) -eq [Convert]::ToUInt64($Session,16) -and [BitConverter]::ToUInt64($lease,16) -gt $now -and [BitConverter]::ToUInt64($lease,16) -le ($now+10000)
        $script:menuLeaseDeadline=if($valid){[BitConverter]::ToUInt64($lease,16)}else{[uint64]0}
        return $valid
    } catch {
        # A missed read retains only the last validated deadline; it never renews it.
        Menu-Trace ('session-read '+$_.Exception.Message)
        return $script:menuLeaseDeadline -gt $now -and $script:menuLeaseDeadline -le ($now+10000)
    }
}
function Menu-Tick {
    if($null -eq $form){return}
    if($Retail){
        if(-not $script:lastStatusTick -or ([DateTime]::UtcNow-$script:lastStatusTick).TotalSeconds -ge 1){Update-CampaignMenu;$script:lastStatusTick=[DateTime]::UtcNow}
    }elseif(-not (Menu-SessionAlive)){$form.Close();return}
    [void][HalfLightMenuWindow]::ClipCursor([IntPtr]::Zero)
    $f7=([HalfLightMenuWindow]::GetAsyncKeyState(0x76) -band 0x8000) -ne 0
    if($f7 -and -not $script:lastF7){$form.Close();return};$script:lastF7=$f7
    if($pending){
        $result=Read-MenuStatus
        if([long]$result.request_sequence -eq $pending -and $result.state -in @('applied','error')){
            $apply.Enabled=$true;$script:pending=0
            if($result.state -eq 'applied'){$message.Text="Equipped successfully.`r`nClose this menu, then press F8 to resume control."}else{$message.Text=$result.error}
            Menu-Trace ('ack '+$result.state)
        }elseif([DateTimeOffset]::UtcNow.ToUnixTimeSeconds()-$sentAt -gt 18){$message.Text='No acknowledgement. Check that Half Sword is in a playable match.';$apply.Enabled=$true;$script:pending=0}
    }
}
function Read-MenuStatus {
    $data=@{}
    $reader=$null;$stream=$null
    try {
        $stream=[IO.File]::Open($statusPath,[IO.FileMode]::Open,[IO.FileAccess]::Read,([IO.FileShare]::ReadWrite -bor [IO.FileShare]::Delete))
        $reader=[IO.StreamReader]::new($stream)
        while($null -ne ($line=$reader.ReadLine())){$pair=$line.Split('=',2);if($pair.Length -eq 2){$data[$pair[0]]=$pair[1]}}
    } catch {} finally {if($reader){$reader.Dispose()}elseif($stream){$stream.Dispose()}}
    if($data.Session -ne $Session){return @{}}
    return $data
}
function Set-WeaponChoices($selector,[string]$family) {
    $previous=$selector.SelectedItem.id
    $selector.BeginUpdate()
    try {
        $selector.Items.Clear()
        foreach($p in $script:profiles){if($p.id -eq 'none' -or $family -eq 'All types' -or $p.family -eq $family){[void]$selector.Items.Add($p)}}
        $selector.SelectedIndex=0
        foreach($p in $selector.Items){if($p.id -eq $previous){$selector.SelectedItem=$p}}
    } finally {$selector.EndUpdate()}
}
function Open-WeaponMenu {
    $catalogPath=Join-Path $taskRoot '.local/catalog.json'
    if(-not (Test-Path -LiteralPath $catalogPath)){$catalogPath=Join-Path $PSScriptRoot 'Weapon-Catalog.json'}
    $catalog=Get-Content $catalogPath -Raw -Encoding UTF8 | ConvertFrom-Json
    if($catalog.version -ne 1 -or $catalog.weapons.Count -lt 1 -or $catalog.weapons.Count -gt 32){throw 'Invalid weapon catalog'}
    $script:profiles=@([pscustomobject]@{id='none';label='Empty';family='Empty'})+@($catalog.weapons)
    $current=Read-MenuStatus
    $script:form=if($Check){New-Object HalfLightMenuPreview}else{New-Object Windows.Forms.Form}
    $form.Text=if($Retail){'HalfLight Weapons and Bridge'}else{'HalfLight Weapons'}
    $form.ClientSize=New-Object Drawing.Size(540,$(if($Retail){650}else{320}))
    $form.FormBorderStyle='FixedDialog';$form.MaximizeBox=$false;$form.MinimizeBox=$false
    $form.StartPosition='CenterParent';$form.TopMost=$true
    $mainLabel=New-Object Windows.Forms.Label;$mainLabel.Text='Main hand (right)';$mainLabel.SetBounds(20,20,235,23)
    $otherLabel=New-Object Windows.Forms.Label;$otherLabel.Text='Other hand (left)';$otherLabel.SetBounds(285,20,235,23)
    $script:mainType=New-Object Windows.Forms.ComboBox;$mainType.DropDownStyle='DropDownList';$mainType.SetBounds(20,48,235,28)
    $script:otherType=New-Object Windows.Forms.ComboBox;$otherType.DropDownStyle='DropDownList';$otherType.SetBounds(285,48,235,28)
    $families=@('All types')+@($catalog.weapons.family | Sort-Object -Unique)
    foreach($family in $families){[void]$mainType.Items.Add($family);[void]$otherType.Items.Add($family)}
    $script:main=New-Object Windows.Forms.ComboBox;$main.DropDownStyle='DropDownList';$main.DisplayMember='label';$main.SetBounds(20,90,235,28)
    $script:other=New-Object Windows.Forms.ComboBox;$other.DropDownStyle='DropDownList';$other.DisplayMember='label';$other.SetBounds(285,90,235,28)
    $mainType.Add_SelectedIndexChanged({Set-WeaponChoices $main ([string]$mainType.SelectedItem)})
    $otherType.Add_SelectedIndexChanged({Set-WeaponChoices $other ([string]$otherType.SelectedItem)})
    $mainType.SelectedIndex=0;$otherType.SelectedIndex=0
    foreach($p in $main.Items){if($p.id -eq $current.right){$main.SelectedItem=$p}}
    foreach($p in $other.Items){if($p.id -eq $current.left){$other.SelectedItem=$p}}
    $script:message=New-Object Windows.Forms.Label;$message.SetBounds(20,143,500,100)
    $message.Text="Choose each hand independently. Two of the same weapon are supported.`r`n`r`nAfter closing, press F8 to resume control."
    $script:apply=New-Object Windows.Forms.Button;$apply.Text='Equip';$apply.SetBounds(315,268,95,32)
    $cancel=New-Object Windows.Forms.Button;$cancel.Text='Close';$cancel.SetBounds(425,268,95,32)
    $apply.Add_Click({
        try {
        if($Retail -and -not $Check -and -not (Menu-SessionAlive)){throw 'Start the bridge and wait for fresh Half Sword poses before equipping.'}
        $script:sequence=[Math]::Max($script:sequence,[long](Read-MenuStatus).request_sequence)+1
        $script:pending=$script:sequence
        $expires=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()+15
        if($null -eq $main.SelectedItem -or $null -eq $other.SelectedItem){throw 'Select a weapon or Empty in each hand'}
        $body="Session=$Session`nseq=$sequence`nend_seq=$sequence`nexpires_at=$expires`nright=$($main.SelectedItem.id)`nleft=$($other.SelectedItem.id)`n"
        [IO.File]::WriteAllText($request+'.tmp',$body,(New-Object Text.UTF8Encoding($false)))
        if(Test-Path $request){[IO.File]::Replace($request+'.tmp',$request,[NullString]::Value)}else{[IO.File]::Move($request+'.tmp',$request)}
        $script:sentAt=[DateTimeOffset]::UtcNow.ToUnixTimeSeconds();$apply.Enabled=$false;$message.Text='Equipping in Half Sword...'
        Menu-Trace ('equip '+$sequence)
        } catch {$message.Text=$_.Exception.Message;Menu-Trace ('error '+$_.Exception.ToString());$apply.Enabled=$true;$script:pending=0}
    })
    $cancel.Add_Click({$form.Close()})
    $form.KeyPreview=$true;$form.Add_KeyDown({if($_.KeyCode -eq 'Escape'){$form.Close()}})
    $form.Add_FormClosed({$script:form=$null;$script:pending=0;$script:bridgeStatus=$null})
    $form.Controls.AddRange(@($mainLabel,$otherLabel,$mainType,$otherType,$main,$other,$message,$apply,$cancel))
    if($Retail){
        $script:startBridge=New-Object Windows.Forms.Button;$startBridge.Text='Start Bridge';$startBridge.SetBounds(20,310,145,32)
        $script:stopBridge=New-Object Windows.Forms.Button;$stopBridge.Text='Stop Bridge';$stopBridge.SetBounds(185,310,145,32)
        $script:restartBridge=New-Object Windows.Forms.Button;$restartBridge.Text='Restart Bridge';$restartBridge.SetBounds(350,310,170,32)
        $startBridge.Add_Click({Request-Bridge 'start'});$stopBridge.Add_Click({Request-Bridge 'stop'});$restartBridge.Add_Click({Request-Bridge 'restart'})
        $script:bridgeStatus=New-Object Windows.Forms.Label;$bridgeStatus.SetBounds(20,355,500,260);$bridgeStatus.Text='Reading bridge status...'
        $hint=New-Object Windows.Forms.Label;$hint.SetBounds(20,615,500,30);$hint.Text='Start/Restart begin with F8 off. The F7 panel stays available after Stop.'
        $form.Controls.AddRange(@($startBridge,$stopBridge,$restartBridge,$bridgeStatus,$hint))
        if(-not $Check){Update-CampaignMenu}
    }
    $form.AcceptButton=$apply;$form.CancelButton=$cancel
    if($Check){
        if($Session -ne '0000000000000000'){throw 'UI checks require the zero test nonce'}
        $main.SelectedIndex=$profiles.Count-1;$other.SelectedIndex=$profiles.Count-1
        if($main.Items.Count -ne $profiles.Count -or $other.Items.Count -ne $profiles.Count){throw 'Catalog selectors differ'}
        foreach($family in @($catalog.weapons.family | Sort-Object -Unique)){
            $mainType.SelectedItem=$family
            if(@($main.Items | Where-Object {$_.id -ne 'none' -and $_.family -ne $family}).Count){throw 'Type filter leaked another family'}
            if($other.Items.Count -ne $profiles.Count){throw 'Main filter changed the other hand'}
        }
        $mainType.SelectedIndex=0;$main.SelectedIndex=$profiles.Count-1
        $expectedId=$main.SelectedItem.id
        $form.StartPosition='Manual';$form.Location=New-Object Drawing.Point(-10000,-10000);$form.ShowInTaskbar=$false
        $form.Show();[Windows.Forms.Application]::DoEvents()
        $bitmap=New-Object Drawing.Bitmap($form.Width,$form.Height)
        $form.CreateControl();$form.DrawToBitmap($bitmap,(New-Object Drawing.Rectangle(0,0,$form.Width,$form.Height)))
        $bitmap.Save((Join-Path $lab $(if($Retail){'campaign-menu-preview.png'}else{'weapon-menu-preview.png'})));$bitmap.Dispose()
        [IO.File]::WriteAllText($request,"existing request`n")
        $apply.PerformClick()
        $written=[IO.File]::ReadAllText($request)
        if($pending -ne 1 -or $apply.Enabled -or $written -notmatch ([regex]::Escape('right='+$expectedId)) -or $written -notmatch ([regex]::Escape('left='+$expectedId))){throw ('Equip click handler failed: '+$message.Text)}
        if($Retail){
            foreach($pair in @(@($startBridge,'start'),@($stopBridge,'stop'),@($restartBridge,'restart'))){
                $pair[0].PerformClick();$writtenRequest=Get-Content (Join-Path $retailDir 'panel-request.json') -Raw | ConvertFrom-Json
                if($writtenRequest.action -ne $pair[1] -or $writtenRequest.sequence -ne $bridgeSequence){throw 'Bridge button request failed'}
            }
            'PASS real Start/Stop/Restart button requests in isolated fixture directory'
        }
        [IO.File]::Delete($request)
        $form.Close();$script:form=$null
        'PASS weapon menu layout, independent type filters/selectors and real Equip click handler'
        return
    }
    $game=Get-Process -Id $TargetPid
    $owner=New-Object HalfLightMenuWindow;$owner.Handle=$game.MainWindowHandle
    $form.Add_Shown({[HalfLightMenuWindow]::FocusMenu($form.Handle);$main.Focus();Menu-Trace 'shown'})
    $form.Add_Activated({Menu-Trace 'activated'})
    $main.Add_SelectedIndexChanged({Menu-Trace ('main '+$main.SelectedIndex)})
    $other.Add_SelectedIndexChanged({Menu-Trace ('other '+$other.SelectedIndex)})
    $script:lastF7=$true
    $timer=New-Object Windows.Forms.Timer;$timer.Interval=50;$timer.Add_Tick({Menu-Tick});$timer.Start()
    $dialog=$form
    try {[void]$dialog.ShowDialog($owner)}finally{$timer.Stop();$timer.Dispose();$dialog.Dispose();$script:form=$null;Menu-Trace 'closed'}
}
if($Check){Open-WeaponMenu;exit 0}
while($true){
    if($script:workerLost){break}
    if($Retail){
        if(-not $script:lastOuterStatus -or ([DateTime]::UtcNow-$script:lastOuterStatus).TotalSeconds -ge .5){Update-CampaignMenu;$script:lastOuterStatus=[DateTime]::UtcNow}
    }elseif(-not (Menu-SessionAlive)){break}
    [uint32]$foregroundPid=0
    [void][HalfLightMenuWindow]::GetWindowThreadProcessId([HalfLightMenuWindow]::GetForegroundWindow(),[ref]$foregroundPid)
    $f7=([HalfLightMenuWindow]::GetAsyncKeyState(0x76) -band 0x8000) -ne 0
    if($f7 -and -not $lastF7){if($null -ne $form){$form.Close()}elseif($foregroundPid -eq $TargetPid){Open-WeaponMenu}}
    $lastF7=$f7
    [Windows.Forms.Application]::DoEvents()
    Start-Sleep -Milliseconds 50
}
if($null -ne $form){$form.Close()}
