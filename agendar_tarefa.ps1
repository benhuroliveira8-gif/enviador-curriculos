# Registra a rotina diária no Agendador de Tarefas do Windows.
#
# Uso (no PowerShell, dentro da pasta do projeto):
#   .\agendar_tarefa.ps1                 # todo dia às 08:47
#   .\agendar_tarefa.ps1 -Hora "07:52"   # outro horário
#   .\agendar_tarefa.ps1 -Remover        # tira do agendador
#
# A tarefa roda com o seu usuário, sem abrir janela. Se o computador estiver desligado
# no horário, ela roda assim que ele for ligado.

param(
    [string]$Hora = "08:47",
    [switch]$Remover
)

$ErrorActionPreference = "Stop"
$Nome = "Enviador de Curriculos - rotina diaria"
$Pasta = $PSScriptRoot

if ($Remover) {
    Unregister-ScheduledTask -TaskName $Nome -Confirm:$false -ErrorAction SilentlyContinue
    Write-Host "Tarefa removida do Agendador."
    exit 0
}

$Pythonw = Join-Path $Pasta ".venv\Scripts\pythonw.exe"
if (-not (Test-Path $Pythonw)) {
    Write-Host "Não encontrei $Pythonw" -ForegroundColor Red
    Write-Host "Crie o ambiente primeiro: py -3.13 -m venv .venv ; .venv\Scripts\activate ; pip install -r requirements.txt"
    exit 1
}
if (-not (Test-Path (Join-Path $Pasta "config.yaml"))) {
    Write-Host "Não encontrei config.yaml nesta pasta." -ForegroundColor Red
    exit 1
}

$Acao = New-ScheduledTaskAction -Execute $Pythonw -Argument "-m enviador diario" -WorkingDirectory $Pasta
$Gatilho = New-ScheduledTaskTrigger -Daily -At $Hora
$Opcoes = New-ScheduledTaskSettingsSet -StartWhenAvailable -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries -RunOnlyIfNetworkAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 1)

Register-ScheduledTask -TaskName $Nome -Action $Acao -Trigger $Gatilho -Settings $Opcoes `
    -Description "Busca vagas, analisa com o currículo e envia um resumo por e-mail." -Force | Out-Null

Write-Host "Pronto! A rotina vai rodar todo dia às $Hora." -ForegroundColor Green
Write-Host "Para testar agora:   Start-ScheduledTask -TaskName '$Nome'"
Write-Host "Resultado de cada dia: pasta relatorios\  |  registro: logs\diario.log"
