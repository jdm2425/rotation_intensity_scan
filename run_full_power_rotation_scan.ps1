# ============================================================
# Full target-power rotation scan
#
# Power:
#   Min mW to Max mW in Step mW increments
#
# Sample rotation:
#   0 degrees to 359 degrees in X degree increments
# ============================================================

$sampleAngles = 327
#$sampleAngles = for ($angle = 0; $angle -le 359; $angle += 1) {
#    $angle
#}
$targetPowers = for ($power = 5; $power -le 10; $power += 0.5) {
	$power
} 

# Replace these with your measured safe monotonic waveplate branch.
$waveplateMinimum = 75
$waveplateMaximum = 114

Write-Host "Sample angles:" $sampleAngles.Count
Write-Host "Target powers:" $targetPowers
Write-Host "Total spectra:" ($sampleAngles.Count * $targetPowers.Count)

python run_target_power_scan.py `
    --sample-angles $sampleAngles `
    --target-powers-mw $targetPowers `
    --waveplate-min-deg $waveplateMinimum `
    --waveplate-max-deg $waveplateMaximum `
    --direction increasing `
    --tolerance-mw 0.25 `
    --maximum-power-mw 30 `
    --integration-time-ms 100 `
    --averages 10 `
    --experiment-name Rubrene-H7-Intensity-Scan `
    --power-calibration results\waveplate_power_control\scan_20260729_160756\malus_calibration_75_114.json