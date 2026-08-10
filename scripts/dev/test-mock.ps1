#Requires -Version 5.1
<#
.SYNOPSIS
    Smoke-test the mock Ollama service at localhost:11434.
    Run after: .\start-dev.ps1 -Mock
#>

$Base = "http://localhost:11434"
$Pass = 0
$Fail = 0

function Test-Endpoint {
    param([string]$Name, [scriptblock]$Check)
    try {
        $result = & $Check
        if ($result) {
            Write-Host "  PASS  $Name" -ForegroundColor Green
            $script:Pass++
        } else {
            Write-Host "  FAIL  $Name" -ForegroundColor Red
            $script:Fail++
        }
    } catch {
        Write-Host "  FAIL  $Name — $($_.Exception.Message)" -ForegroundColor Red
        $script:Fail++
    }
}

Write-Host ""
Write-Host "Testing mock Ollama at $Base" -ForegroundColor Cyan
Write-Host ("-" * 50)

# GET /api/tags
Test-Endpoint "GET /api/tags returns 3 models" {
    $r = Invoke-RestMethod "$Base/api/tags"
    $r.models.Count -eq 3
}

# GET /api/ps
Test-Endpoint "GET /api/ps returns 1 loaded model" {
    $r = Invoke-RestMethod "$Base/api/ps"
    $r.models.Count -ge 1
}

# POST /api/chat — non-streaming
Test-Endpoint "POST /api/chat (stream:false) returns message" {
    $body = @{ model = "qwen2.5:14b"; messages = @(@{ role = "user"; content = "hello" }); stream = $false } | ConvertTo-Json
    $r = Invoke-RestMethod "$Base/api/chat" -Method Post -Body $body -ContentType "application/json"
    $r.done -eq $true -and $r.message.content -match "MOCK RESPONSE"
}

# POST /api/chat — streaming (read first line of NDJSON)
Test-Endpoint "POST /api/chat (stream:true) streams NDJSON" {
    $body = @{ model = "qwen2.5:14b"; messages = @(@{ role = "user"; content = "stream test" }); stream = $true } | ConvertTo-Json -Compress
    $req = [System.Net.WebRequest]::Create("$Base/api/chat")
    $req.Method = "POST"
    $req.ContentType = "application/json"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $req.ContentLength = $bytes.Length
    $req.GetRequestStream().Write($bytes, 0, $bytes.Length)
    $resp = $req.GetResponse()
    $reader = [System.IO.StreamReader]::new($resp.GetResponseStream())
    $firstLine = $reader.ReadLine()
    $reader.Close()
    $resp.Close()
    $chunk = $firstLine | ConvertFrom-Json
    $chunk.message -ne $null
}

# POST /api/pull
Test-Endpoint "POST /api/pull streams progress" {
    $body = @{ name = "qwen2.5:14b" } | ConvertTo-Json -Compress
    $req = [System.Net.WebRequest]::Create("$Base/api/pull")
    $req.Method = "POST"
    $req.ContentType = "application/json"
    $bytes = [System.Text.Encoding]::UTF8.GetBytes($body)
    $req.ContentLength = $bytes.Length
    $req.GetRequestStream().Write($bytes, 0, $bytes.Length)
    $resp = $req.GetResponse()
    $reader = [System.IO.StreamReader]::new($resp.GetResponseStream())
    $firstLine = $reader.ReadLine()
    $reader.Close()
    $resp.Close()
    $chunk = $firstLine | ConvertFrom-Json
    $chunk.status -ne $null
}

# DELETE /api/delete
Test-Endpoint "DELETE /api/delete returns 200" {
    $body = @{ name = "qwen2.5:14b" } | ConvertTo-Json
    try {
        Invoke-RestMethod "$Base/api/delete" -Method Delete -Body $body -ContentType "application/json" | Out-Null
        $true
    } catch [System.Net.WebException] {
        # 200 with empty body sometimes throws; check status code
        [int]$_.Exception.Response.StatusCode -eq 200
    }
}

# POST /v1/chat/completions (OpenAI-compatible)
Test-Endpoint "POST /v1/chat/completions returns choice" {
    $body = @{ model = "qwen2.5:14b"; messages = @(@{ role = "user"; content = "hello openai" }); stream = $false } | ConvertTo-Json
    $r = Invoke-RestMethod "$Base/v1/chat/completions" -Method Post -Body $body -ContentType "application/json"
    $r.choices.Count -ge 1 -and $r.choices[0].message.content -match "MOCK RESPONSE"
}

# GET /health
Test-Endpoint "GET /health returns ok" {
    $r = Invoke-RestMethod "$Base/health"
    $r.status -eq "ok"
}

Write-Host ("-" * 50)
$total = $Pass + $Fail
if ($Fail -eq 0) {
    Write-Host "All $total tests passed." -ForegroundColor Green
} else {
    Write-Host "$Pass/$total passed, $Fail failed." -ForegroundColor Red
}
Write-Host ""
exit ($Fail -gt 0 ? 1 : 0)
