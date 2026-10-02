"""Hardware-free tests for portable multi-session campaign projects."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile

from experiments.waveplate_calibration import MalusLawCalibration
from gui.campaign_project import CampaignProject


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="campaign_project_") as temporary:
        temporary_root = Path(temporary)
        original_root = temporary_root / "computer_a" / "campaign"
        project = CampaignProject.create(
            original_root / "October campaign.risproject",
            name="October campaign",
        )
        assert project.runs_directory.is_dir()
        assert project.calibrations_directory.is_dir()
        assert project.live_spectra_directory.is_dir()

        project.set_scan_settings(
            {
                "sample_angles": "0 10 20",
                "spectra_per_point": 3,
                "acquire_background": True,
            }
        )
        calibration_path = (
            project.calibrations_directory
            / "calibration_20261002_120000"
            / "malus_calibration.json"
        )
        MalusLawCalibration(
            constant_mw=5.0,
            cosine_mw=2.0,
            sine_mw=1.0,
            waveplate_min_deg=70.0,
            waveplate_max_deg=100.0,
            monotonic_direction="increasing",
            rms_residual_mw=0.1,
            point_count=8,
        ).save(calibration_path)
        project.record_calibration(calibration_path)

        run_directory = project.runs_directory / "day_1_run_20261002_120100"
        run_directory.mkdir()
        project.record_run(run_directory)
        project.record_run(run_directory)
        recovered_run = project.runs_directory / "day_2_run_20261003_090000"
        recovered_run.mkdir()
        (recovered_run / "measurements.csv").write_text(
            "measurement,spectrum_file\n", encoding="utf-8"
        )
        project.save()

        with project.path.open("r", encoding="utf-8") as file:
            raw = json.load(file)
        assert not Path(raw["paths"]["runs"]).is_absolute()
        assert not Path(raw["active_calibration"]).is_absolute()
        assert len(raw["run_directories"]) == 1
        assert not project.path.with_suffix(".risproject.tmp").exists()

        moved_root = temporary_root / "computer_b" / "campaign"
        moved_root.parent.mkdir(parents=True)
        shutil.move(str(original_root), str(moved_root))
        moved_project = CampaignProject.load(
            moved_root / "October campaign.risproject"
        )
        assert moved_project.active_calibration is not None
        assert moved_project.active_calibration.is_file()
        assert moved_project.latest_run is not None
        assert moved_project.latest_run == (
            moved_project.runs_directory / "day_2_run_20261003_090000"
        )
        assert len(moved_project.run_directories) == 2
        assert moved_project.scan_settings["spectra_per_point"] == 3

        escaped = json.loads(moved_project.path.read_text(encoding="utf-8"))
        escaped["paths"]["runs"] = "../outside"
        moved_project.path.write_text(json.dumps(escaped), encoding="utf-8")
        try:
            CampaignProject.load(moved_project.path)
        except ValueError as error:
            assert "escapes" in str(error)
        else:
            raise AssertionError("Escaping project path was accepted.")

    print("CAMPAIGN PROJECT TEST PASSED")


if __name__ == "__main__":
    main()
