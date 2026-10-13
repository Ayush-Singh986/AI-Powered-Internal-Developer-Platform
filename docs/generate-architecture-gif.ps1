Add-Type -AssemblyName System.Drawing

$width = 1100
$height = 675
$scale = $width / 1500.0
$frameCount = 16
$outputPath = Join-Path $PSScriptRoot "ai-idp-architecture.gif"
$background = [System.Drawing.Color]::FromArgb(11, 18, 32)
$muted = [System.Drawing.Color]::FromArgb(154, 171, 194)
$white = [System.Drawing.Color]::FromArgb(235, 243, 255)
$blue = [System.Drawing.Color]::FromArgb(66, 153, 225)
$cyan = [System.Drawing.Color]::FromArgb(56, 189, 248)
$green = [System.Drawing.Color]::FromArgb(52, 211, 153)
$orange = [System.Drawing.Color]::FromArgb(251, 146, 60)
$purple = [System.Drawing.Color]::FromArgb(167, 139, 250)
$red = [System.Drawing.Color]::FromArgb(248, 113, 113)
$teal = [System.Drawing.Color]::FromArgb(45, 212, 191)
$card = [System.Drawing.Color]::FromArgb(20, 31, 51)
$darkCard = [System.Drawing.Color]::FromArgb(15, 25, 43)
$lineColor = [System.Drawing.Color]::FromArgb(80, 102, 132)

function Draw-Text($graphics, $text, $x, $y, $w, $h, $size, $color, $bold = $false, $center = $false) {
    $style = [System.Drawing.FontStyle]::Regular
    if ($bold) { $style = [System.Drawing.FontStyle]::Bold }
    $font = New-Object System.Drawing.Font("Segoe UI", $size, $style, [System.Drawing.GraphicsUnit]::Pixel)
    $brush = New-Object System.Drawing.SolidBrush($color)
    $format = New-Object System.Drawing.StringFormat
    if ($center) { $format.Alignment = [System.Drawing.StringAlignment]::Center }
    $format.LineAlignment = [System.Drawing.StringAlignment]::Center
    $graphics.DrawString($text, $font, $brush, [System.Drawing.RectangleF]::new($x, $y, $w, $h), $format)
    $font.Dispose()
    $brush.Dispose()
    $format.Dispose()
}

function Draw-RoundedBox($graphics, $x, $y, $w, $h, $fill, $stroke, $radius = 16) {
    $path = New-Object System.Drawing.Drawing2D.GraphicsPath
    $diameter = $radius * 2
    $path.AddArc($x, $y, $diameter, $diameter, 180, 90)
    $path.AddArc($x + $w - $diameter, $y, $diameter, $diameter, 270, 90)
    $path.AddArc($x + $w - $diameter, $y + $h - $diameter, $diameter, $diameter, 0, 90)
    $path.AddArc($x, $y + $h - $diameter, $diameter, $diameter, 90, 90)
    $path.CloseFigure()
    $fillBrush = New-Object System.Drawing.SolidBrush($fill)
    $strokePen = New-Object System.Drawing.Pen($stroke, 2)
    $graphics.FillPath($fillBrush, $path)
    $graphics.DrawPath($strokePen, $path)
    $fillBrush.Dispose()
    $strokePen.Dispose()
    $path.Dispose()
}

function Draw-Card($graphics, $x, $y, $w, $h, $title, $detail, $accent) {
    Draw-RoundedBox $graphics $x $y $w $h $card $accent 14
    $bar = New-Object System.Drawing.SolidBrush($accent)
    $graphics.FillRectangle($bar, $x + 14, $y + 16, 5, $h - 32)
    $bar.Dispose()
    Draw-Text $graphics $title ($x + 30) ($y + 10) ($w - 40) 30 18 $white $true
    Draw-Text $graphics $detail ($x + 30) ($y + 42) ($w - 40) ($h - 48) 15 $muted
}

function Draw-Route($graphics, $points, $color, $label = "", $labelX = 0, $labelY = 0, $dashed = $false) {
    $pen = New-Object System.Drawing.Pen($color, 2)
    $pen.StartCap = [System.Drawing.Drawing2D.LineCap]::Round
    $pen.EndCap = [System.Drawing.Drawing2D.LineCap]::Round
    if ($dashed) { $pen.DashStyle = [System.Drawing.Drawing2D.DashStyle]::Dash }
    for ($i = 0; $i -lt $points.Count - 1; $i++) {
        $graphics.DrawLine($pen, $points[$i][0], $points[$i][1], $points[$i + 1][0], $points[$i + 1][1])
    }
    $last = $points[$points.Count - 1]
    $previous = $points[$points.Count - 2]
    $angle = [Math]::Atan2($last[1] - $previous[1], $last[0] - $previous[0])
    $arrowLength = 10
    $left = [System.Drawing.PointF]::new(
        $last[0] - $arrowLength * [Math]::Cos($angle - 0.48),
        $last[1] - $arrowLength * [Math]::Sin($angle - 0.48)
    )
    $right = [System.Drawing.PointF]::new(
        $last[0] - $arrowLength * [Math]::Cos($angle + 0.48),
        $last[1] - $arrowLength * [Math]::Sin($angle + 0.48)
    )
    $graphics.DrawLine($pen, $last[0], $last[1], $left.X, $left.Y)
    $graphics.DrawLine($pen, $last[0], $last[1], $right.X, $right.Y)
    $pen.Dispose()
    if ($label) {
        Draw-Text $graphics $label $labelX $labelY 200 24 13 $color $true
    }
}

function Get-RoutePoint($points, $progress) {
    $lengths = @()
    $total = 0.0
    for ($i = 0; $i -lt $points.Count - 1; $i++) {
        $dx = $points[$i + 1][0] - $points[$i][0]
        $dy = $points[$i + 1][1] - $points[$i][1]
        $segment = [Math]::Sqrt($dx * $dx + $dy * $dy)
        $lengths += $segment
        $total += $segment
    }
    $distance = $progress * $total
    for ($i = 0; $i -lt $lengths.Count; $i++) {
        if ($distance -le $lengths[$i] -or $i -eq $lengths.Count - 1) {
            $ratio = 0.0
            if ($lengths[$i] -gt 0) { $ratio = [Math]::Min(1.0, $distance / $lengths[$i]) }
            $x = $points[$i][0] + ($points[$i + 1][0] - $points[$i][0]) * $ratio
            $y = $points[$i][1] + ($points[$i + 1][1] - $points[$i][1]) * $ratio
            return @($x, $y)
        }
        $distance -= $lengths[$i]
    }
}

$routes = @(
    @{ Points = @(@(220, 190), @(280, 190)); Color = $cyan; Offset = 0.00 },
    @{ Points = @(@(485, 190), @(550, 190)); Color = $blue; Offset = 0.18 },
    @{ Points = @(@(750, 190), @(820, 190)); Color = $orange; Offset = 0.36 },
    @{ Points = @(@(650, 228), @(650, 250), @(380, 250), @(380, 228)); Color = $blue; Offset = 0.42 },
    @{ Points = @(@(365, 228), @(365, 285), @(1280, 285), @(1280, 408)); Color = $purple; Offset = 0.52 },
    @{ Points = @(@(915, 228), @(915, 355), @(980, 410)); Color = $orange; Offset = 0.68 },
    @{ Points = @(@(1280, 465), @(1280, 490)); Color = $purple; Offset = 0.82 },
    @{ Points = @(@(960, 508), @(985, 508), @(985, 580), @(1000, 580)); Color = $green; Offset = 0.12 },
    @{ Points = @(@(1092, 590), @(1092, 615)); Color = $orange; Offset = 0.34 },
    @{ Points = @(@(1275, 685), @(1275, 700), @(980, 700), @(980, 759)); Color = $red; Offset = 0.57 },
    @{ Points = @(@(1000, 700), @(890, 700), @(890, 725)); Color = $teal; Offset = 0.78 },
    @{ Points = @(@(980, 759), @(1185, 759)); Color = $teal; Offset = 0.46 },
    @{ Points = @(@(345, 515), @(425, 515)); Color = $purple; Offset = 0.06 }
)

$codec = [System.Drawing.Imaging.ImageCodecInfo]::GetImageEncoders() | Where-Object { $_.MimeType -eq "image/gif" }
$saveFlag = [System.Drawing.Imaging.Encoder]::SaveFlag
$dimension = [System.Drawing.Imaging.FrameDimension]::Time
$master = $null

for ($frameIndex = 0; $frameIndex -lt $frameCount; $frameIndex++) {
    $bitmap = New-Object System.Drawing.Bitmap($width, $height, [System.Drawing.Imaging.PixelFormat]::Format24bppRgb)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $graphics.SmoothingMode = [System.Drawing.Drawing2D.SmoothingMode]::AntiAlias
    $graphics.TextRenderingHint = [System.Drawing.Text.TextRenderingHint]::AntiAliasGridFit
    $graphics.ScaleTransform($scale, $scale)
    $graphics.Clear($background)

    Draw-Text $graphics "AI-POWERED INTERNAL DEVELOPER PLATFORM" 48 28 1050 42 30 $white $true
    Draw-Text $graphics "AWS EKS deployment | CI/CD delivery | AI services | observability" 50 72 1100 30 17 $muted
    Draw-Text $graphics "ARCHITECTURE FLOW" 1260 43 190 24 13 $cyan $true

    Draw-Route $graphics @(@(220, 190), @(280, 190)) $cyan "git push" 222 158
    Draw-Route $graphics @(@(485, 190), @(550, 190)) $blue "webhook" 480 158
    Draw-Route $graphics @(@(750, 190), @(820, 190)) $orange "publish" 750 158

    Draw-RoundedBox $graphics 425 320 1000 555 ([System.Drawing.Color]::FromArgb(13, 35, 47)) $teal 24
    Draw-Text $graphics "AWS  |  ap-south-1" 455 332 480 35 23 $teal $true
    Draw-Text $graphics "VPC  |  2 Availability Zones  |  public/private subnets  |  NAT gateway" 455 369 800 25 14 $muted

    Draw-Card $graphics 48 150 172 78 "Developer" "pushes code" $cyan
    Draw-Card $graphics 280 150 205 78 "GitHub Repo" "source + GitOps" $blue
    Draw-Card $graphics 550 150 200 78 "Jenkins CI" "test | build | Trivy scan" $orange
    Draw-Card $graphics 820 150 190 78 "GHCR" "five service images" $orange

    Draw-Card $graphics 45 465 300 100 "Terraform" "VPC | EKS | S3" $purple
    Draw-Card $graphics 465 485 190 90 "Amazon S3" "versioned, encrypted\nartifact bucket" $green
    Draw-RoundedBox $graphics 690 405 710 430 ([System.Drawing.Color]::FromArgb(12, 26, 44)) $blue 20
    Draw-Text $graphics "AMAZON EKS  |  Kubernetes 1.35" 720 414 450 32 21 $blue $true
    Draw-Text $graphics "Managed nodes | default 2 x t3.large EC2" 720 447 450 24 14 $muted

    Draw-RoundedBox $graphics 1000 480 375 205 $darkCard $lineColor 15
    Draw-Text $graphics "PLATFORM SERVICES" 1018 487 330 24 13 $muted $true
    Draw-RoundedBox $graphics 735 690 640 125 $darkCard $lineColor 15
    Draw-Text $graphics "OBSERVABILITY" 755 696 250 23 13 $muted $true

    Draw-Route $graphics @(@(365, 228), @(365, 285), @(1280, 285), @(1280, 408)) $purple "GitOps poll" 680 260 $true
    Draw-Route $graphics @(@(915, 228), @(915, 355), @(980, 410)) $orange
    Draw-Route $graphics @(@(650, 228), @(650, 250), @(380, 250), @(380, 228)) $blue "commit tags" 500 229 $true
    Draw-Route $graphics @(@(345, 515), @(425, 515)) $purple "provision" 344 480
    Draw-Route $graphics @(@(1280, 465), @(1280, 490)) $purple "sync" 1290 466
    Draw-Route $graphics @(@(960, 508), @(985, 508), @(985, 580), @(1000, 580)) $green "HTTP API" 970 545
    Draw-Route $graphics @(@(1092, 590), @(1092, 615)) $orange "LLM" 1100 587
    Draw-Route $graphics @(@(1275, 685), @(1275, 700), @(980, 700), @(980, 759)) $red "PromQL" 1170 682
    Draw-Route $graphics @(@(1000, 700), @(890, 700), @(890, 725)) $teal "/metrics" 910 690

    Draw-Card $graphics 735 470 225 76 "Forge Portal" "FastAPI | Three.js | :8501" $cyan
    Draw-Card $graphics 1185 408 190 57 "Argo CD" "App-of-Apps | GitOps" $purple
    Draw-Card $graphics 1010 520 165 70 "Docs RAG" "docs-assistant" $blue
    Draw-Card $graphics 1190 520 170 70 "Risk Model" "model-serving" $purple
    Draw-Card $graphics 1010 615 165 70 "LLM Gateway" "cache | tokens | cost" $orange
    Draw-Card $graphics 1190 615 170 70 "AIOps Agent" "incidents | PromQL" $red

    Draw-Card $graphics 800 725 180 68 "Prometheus" "metrics | :9090" $teal
    Draw-Card $graphics 1185 725 160 68 "Grafana" "Mission Control | :3000" $teal
    Draw-Route $graphics @(@(980, 759), @(1185, 759)) $teal "datasource" 1020 727

    Draw-Text $graphics "Terraform provisions AWS; Jenkins is configured separately." 48 850 1000 28 14 $muted
    Draw-Text $graphics "GHCR images are pulled by EKS | Argo CD applies GitOps manifests" 945 850 500 28 13 $muted $false $true

    foreach ($route in $routes) {
        $progress = (($frameIndex / $frameCount) + $route.Offset) % 1.0
        $point = Get-RoutePoint $route.Points $progress
        $glow = New-Object System.Drawing.SolidBrush([System.Drawing.Color]::FromArgb(55, $route.Color))
        $dot = New-Object System.Drawing.SolidBrush($route.Color)
        $graphics.FillEllipse($glow, $point[0] - 9, $point[1] - 9, 18, 18)
        $graphics.FillEllipse($dot, $point[0] - 4, $point[1] - 4, 8, 8)
        $glow.Dispose()
        $dot.Dispose()
    }

    $graphics.Dispose()
    if ($frameIndex -eq 0) {
        $master = $bitmap.Clone()
        $frameDelay = [System.Runtime.Serialization.FormatterServices]::GetUninitializedObject([System.Drawing.Imaging.PropertyItem])
        $frameDelay.Id = 0x5100
        $frameDelay.Type = 4
        $frameDelay.Len = $frameCount * 4
        $frameDelay.Value = New-Object byte[] ($frameCount * 4)
        for ($delayIndex = 0; $delayIndex -lt $frameCount; $delayIndex++) {
            $frameDelay.Value[$delayIndex * 4] = 12
        }
        $master.SetPropertyItem($frameDelay)
        $frameDisposal = [System.Runtime.Serialization.FormatterServices]::GetUninitializedObject([System.Drawing.Imaging.PropertyItem])
        $frameDisposal.Id = 0x5101
        $frameDisposal.Type = 3
        $frameDisposal.Len = $frameCount * 2
        $frameDisposal.Value = New-Object byte[] ($frameCount * 2)
        for ($disposalIndex = 0; $disposalIndex -lt $frameCount; $disposalIndex++) {
            $frameDisposal.Value[$disposalIndex * 2] = 2
        }
        $master.SetPropertyItem($frameDisposal)
        $parameters = New-Object System.Drawing.Imaging.EncoderParameters(1)
        $parameters.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter($saveFlag, [long][System.Drawing.Imaging.EncoderValue]::MultiFrame)
        $master.Save($outputPath, $codec, $parameters)
        $parameters.Dispose()
    } else {
        $parameters = New-Object System.Drawing.Imaging.EncoderParameters(1)
        $parameters.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter($saveFlag, [long][System.Drawing.Imaging.EncoderValue]::FrameDimensionTime)
        $master.SaveAdd($bitmap, $parameters)
        $parameters.Dispose()
    }
    $bitmap.Dispose()
}

$flush = New-Object System.Drawing.Imaging.EncoderParameters(1)
$flush.Param[0] = New-Object System.Drawing.Imaging.EncoderParameter($saveFlag, [long][System.Drawing.Imaging.EncoderValue]::Flush)
$master.SaveAdd($flush)
$flush.Dispose()
if ($master) { $master.Dispose() }
Write-Output "Created $outputPath"
