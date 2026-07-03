# Windows 任务计划程序注册脚本
# 以管理员身份运行 PowerShell，执行此脚本即可创建每日签到定时任务
# 使用方法: powershell -ExecutionPolicy Bypass -File setup_scheduled_task.ps1

$taskName = "聚合API每日签到"
$scriptPath = Join-Path $PSScriptRoot "daily_checkin.bat"
$pythonPath = Join-Path $PSScriptRoot "daily_checkin.py"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  聚合API 每日签到 - 任务计划程序设置" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 检查脚本是否存在
if (-not (Test-Path $pythonPath)) {
    Write-Host "[错误] 找不到 $pythonPath" -ForegroundColor Red
    exit 1
}

Write-Host "[信息] 脚本路径: $pythonPath" -ForegroundColor Green
Write-Host ""

# 选择触发时间
$scheduleTime = Read-Host "请输入每日签到时间 (格式 HH:MM，默认 21:00)"
if ([string]::IsNullOrWhiteSpace($scheduleTime)) {
    $scheduleTime = "21:00"
}

$parts = $scheduleTime -split ":"
$hour = [int]$parts[0]
$minute = [int]$parts[1]

# 删除已有任务(如果存在)
$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "[信息] 已存在同名任务，正在删除..." -ForegroundColor Yellow
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

# 创建任务操作
$action = New-ScheduledTaskAction -Execute "python" -Argument "`"$pythonPath`"" -WorkingDirectory $PSScriptRoot

# 创建触发器 (每天指定时间)
$trigger = New-ScheduledTaskTrigger -Daily -At "$scheduleTime"

# 创建任务设置
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -MultipleInstances IgnoreNew

# 注册任务
try {
    Register-ScheduledTask -TaskName $taskName `
        -Action $action `
        -Trigger $trigger `
        -Settings $settings `
        -Description "每日打开UC/Chrome/Edge浏览器跳转到 aiyiwei.vip 进行签到" `
        -RunLevel Highest `
        -Force
    
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  ✓ 任务计划已创建成功!" -ForegroundColor Green
    Write-Host "========================================" -ForegroundColor Green
    Write-Host "  任务名称: $taskName"
    Write-Host "  执行时间: 每天 $scheduleTime"
    Write-Host "  执行脚本: $pythonPath"
    Write-Host ""
    Write-Host "  管理方式: 打开 '任务计划程序' (taskschd.msc)" -ForegroundColor Yellow
    Write-Host "  手动测试: 右键任务 → 运行" -ForegroundColor Yellow
    Write-Host ""
} catch {
    Write-Host "[错误] 创建任务失败: $_" -ForegroundColor Red
    Write-Host "[提示] 请以管理员身份运行此脚本" -ForegroundColor Yellow
}
