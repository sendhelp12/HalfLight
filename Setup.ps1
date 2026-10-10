$ErrorActionPreference='Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$releaseRoot=$PSScriptRoot
$privateRoot=Join-Path $releaseRoot '.local'
function Find-SteamGames {
    $libraries=@()
    foreach($key in @('HKCU:\Software\Valve\Steam','HKLM:\SOFTWARE\WOW6432Node\Valve\Steam')) {
        $item=Get-ItemProperty -LiteralPath $key -ErrorAction SilentlyContinue
        foreach($property in @('SteamPath','InstallPath')) {
            if($item.$property){$libraries+=$item.$property}
        }
    }
    foreach($library in @($libraries)) {
        $vdf=Join-Path $library 'steamapps\libraryfolders.vdf'
        if(Test-Path -LiteralPath $vdf) {
            foreach($match in [regex]::Matches((Get-Content -LiteralPath $vdf -Raw),'"path"\s+"([^"]+)"')) {
                $libraries+=$match.Groups[1].Value.Replace('\\','\')
            }
        }
    }
    $found=@{}
    foreach($library in ($libraries | Select-Object -Unique)) {
        foreach($name in @('Half Sword','Dying Light 2')) {
            $candidate=Join-Path $library ('steamapps\common\'+$name)
            if(Test-Path -LiteralPath $candidate -PathType Container){$found[$name]=$candidate}
        }
    }
    return $found
}
function Get-LocalPython {
    $folder=Join-Path $privateRoot 'python'
    $python=Join-Path $folder 'python.exe'
    if(-not (Test-Path -LiteralPath $python)){
    New-Item -ItemType Directory -Path $privateRoot -Force | Out-Null
    $archive=Join-Path $privateRoot 'python.zip'
    # Exact official archive, verified before any executable is launched.
    Invoke-WebRequest -UseBasicParsing -Uri 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-embed-amd64.zip' -OutFile $archive
    $algorithm=[Security.Cryptography.SHA256]::Create();$stream=[IO.File]::OpenRead($archive)
    try{$hash=[BitConverter]::ToString($algorithm.ComputeHash($stream)).Replace('-','')}finally{$stream.Dispose();$algorithm.Dispose()}
    if($hash -ne '4ACBED6DD1C744B0376E3B1CF57CE906F9DC9E95E68824584C8099A63025A3C3') {
        throw 'Python download verification failed. Nothing was installed into either game.'
    }
    Expand-Archive -LiteralPath $archive -DestinationPath $folder -Force
    }
    $pathFile=Join-Path $folder 'python312._pth'
    $paths=Get-Content -LiteralPath $pathFile
    foreach($entry in @('../../work','../../outputs/HalfLightNext','../tools/capstone')){
        if($paths -notcontains $entry){Add-Content -LiteralPath $pathFile -Value $entry}
    }
    return $python
}
$form=New-Object Windows.Forms.Form
$form.Text='HalfLight Setup'
$form.ClientSize=New-Object Drawing.Size(680,345)
$form.StartPosition='CenterScreen'
$form.FormBorderStyle='FixedDialog';$form.MaximizeBox=$false
$intro=New-Object Windows.Forms.Label
$intro.Text='Choose your own installations. Setup builds the bridge and extracts weapons locally. Open each game only once when setup asks; keep this window open.'
$intro.Location=New-Object Drawing.Point(18,15);$intro.Size=New-Object Drawing.Size(640,48)
$form.Controls.Add($intro)
$games=Find-SteamGames
$inputs=@{}
$y=75
foreach($name in @('Half Sword','Dying Light 2')) {
    $label=New-Object Windows.Forms.Label;$label.Text=$name;$label.Location=New-Object Drawing.Point(18,$y)
    $form.Controls.Add($label)
    $box=New-Object Windows.Forms.TextBox;$box.Location=New-Object Drawing.Point(18,($y+23));$box.Size=New-Object Drawing.Size(545,25)
    if($games[$name]){$box.Text=$games[$name]}
    $inputs[$name]=$box;$form.Controls.Add($box)
    $browse=New-Object Windows.Forms.Button;$browse.Text='Browse';$browse.Location=New-Object Drawing.Point(575,($y+21))
    $browse.Tag=$box
    $browse.Add_Click({$dialog=New-Object Windows.Forms.FolderBrowserDialog;if($dialog.ShowDialog() -eq 'OK'){$this.Tag.Text=$dialog.SelectedPath};$dialog.Dispose()})
    $form.Controls.Add($browse);$y+=75
}
$status=New-Object Windows.Forms.Label;$status.Location=New-Object Drawing.Point(18,228);$status.Size=New-Object Drawing.Size(640,60)
$status.Text='Games can stay closed for this check. No save files or game files will change.';$form.Controls.Add($status)
$check=New-Object Windows.Forms.Button;$check.Text='Check installations';$check.Location=New-Object Drawing.Point(18,298);$check.Size=New-Object Drawing.Size(185,32)
$install=New-Object Windows.Forms.Button;$install.Text='Install / Resume';$install.Location=New-Object Drawing.Point(220,298);$install.Size=New-Object Drawing.Size(205,32)
$install.Enabled=$false
$script:setupWorker=$null
$install.Add_Click({
    $install.Enabled=$false;$check.Enabled=$false;$status.Text='Preparing local installation…';$form.Refresh()
    try {
        $python=Get-LocalPython
        $config=Get-Content -LiteralPath (Join-Path $privateRoot 'install.json') -Raw | ConvertFrom-Json
        if($config.ready){
            & $python (Join-Path $releaseRoot 'work\campaign_control.py') 'start'
            if($LASTEXITCODE -ne 0){throw 'Bridge could not start; see F7 status.'}
            $status.Text='Bridge started. F7 opens its controls and status; F8 enables weapon control.'
            $check.Enabled=$true;$install.Enabled=$true;return
        }
        $action='all';if($config.capture_session){$action='finish'}
        $script:setupWorker=Start-Process -FilePath $python -ArgumentList @(('"'+(Join-Path $releaseRoot 'work\complete_setup.py')+'"'),$action) -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $privateRoot 'setup-output.log') -RedirectStandardError (Join-Path $privateRoot 'setup-error.log')
    } catch {
        $status.Text='Setup stopped. See the error below.'
        [Windows.Forms.MessageBox]::Show($_.Exception.Message,'HalfLight Setup') | Out-Null
        $check.Enabled=$true;$install.Enabled=$true
    }
})
$form.Controls.Add($install)
$check.Add_Click({
    $check.Enabled=$false;$status.Text='Checking local installations and downloading the verified Python runtime if needed…';$form.Refresh()
    try {
        $python=Get-LocalPython
        $output=& $python (Join-Path $releaseRoot 'work\setup.py') '--half-sword' $inputs['Half Sword'].Text '--dying-light' $inputs['Dying Light 2'].Text 2>&1
        if($LASTEXITCODE -ne 0){throw ($output -join "`n")}
        $status.Text='Compatibility checks passed. Close both games for loader installation, then click Install. Setup will ask you to open them once.'
        $install.Enabled=$true
    } catch {
        $status.Text='Check failed. No game files changed.'
        [Windows.Forms.MessageBox]::Show($_.Exception.Message,'HalfLight Setup') | Out-Null
    } finally {$check.Enabled=$true}
})
$form.Controls.Add($check)
$timer=New-Object Windows.Forms.Timer;$timer.Interval=500
$timer.Add_Tick({
    if($null -eq $script:setupWorker){return}
    try{
        $config=Get-Content -LiteralPath (Join-Path $privateRoot 'install.json') -Raw | ConvertFrom-Json
        $status.Text=$config.note
    }catch{}
    if($script:setupWorker.HasExited){
        if($script:setupWorker.ExitCode -ne 0){
            $status.Text='Setup stopped: '+$config.note+'. Fix the reported prerequisite, then click Resume.'
        }
        $script:setupWorker.Dispose();$script:setupWorker=$null
        $check.Enabled=$true;$install.Enabled=$true
    }
})
$timer.Start()
if(Test-Path -LiteralPath (Join-Path $privateRoot 'install.json')){$install.Enabled=$true}
[void]$form.ShowDialog();$timer.Stop();$timer.Dispose();$form.Dispose()
