# ============================================================
# Full target-power rotation scan
#
# Power:
#   1 mW to 10 mW in 1 mW increments
#
# Sample rotation:
#   0 degrees to 359 degrees in 5 degree increments
# ============================================================

# $sampleAngles = 0..359
$sampleAngles = for ($angle = 0; $angle -le 359; $angle += 5) {
    $angle
}
$targetPowers = 1..10

# Replace these with your measured safe monotonic waveplate branch.
$waveplateMinimum = 66
$waveplateMaximum = 109

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
    --experiment-name Rubrene-power-1-to-10mW-rotation-0-to-359deg