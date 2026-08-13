"""Human- and machine-readable reporting for offline harmonic analysis."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from analysis.harmonic_analysis import HarmonicResult


BACKGROUND_USED = "used"
BACKGROUND_EXPLICITLY_NOT_USED = "explicitly_not_used"
BACKGROUND_NOT_SPECIFIED = "not_specified"

TRANSMISSION_SCALAR = "scalar_fraction"
TRANSMISSION_CURVE = "curve"
TRANSMISSION_EXPLICITLY_NOT_USED = "explicitly_not_used"
TRANSMISSION_NOT_SPECIFIED = "not_specified"


@dataclass(frozen=True, slots=True)
class AnalysisWarning:
    """One actionable analysis-provenance or data-quality warning."""

    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def installed_filter_names(experimental_metadata: dict) -> list[str]:
    """Return readable installed-filter names from saved experiment metadata."""

    filters = experimental_metadata.get("filters", [])
    if not isinstance(filters, list):
        return []

    names: list[str] = []
    for index, filter_record in enumerate(filters, start=1):
        if isinstance(filter_record, dict):
            name = str(filter_record.get("name", "")).strip()
            part_number = str(filter_record.get("part_number", "")).strip()
            if name and part_number and part_number.lower() not in name.lower():
                label = f"{name} ({part_number})"
            else:
                label = name or part_number
        else:
            label = str(filter_record).strip()
        names.append(label or f"unnamed filter {index}")
    return names


def build_quality_summary(
    results: Iterable[HarmonicResult],
    *,
    power_attempts: Iterable[object] = (),
) -> dict[str, int]:
    """Summarise quality flags and power-statistics coverage."""

    rows = tuple(results)
    attempts = tuple(power_attempts)
    measurement_numbers = {row.measurement_number for row in rows}
    saturated_measurements = {
        row.measurement_number for row in rows if row.saturated
    }
    target_power_rows = [
        row for row in rows if getattr(row, "target_power_mw", None) is not None
    ]
    failed_power_measurements = {
        getattr(row, "power_measurement_id", None) or row.measurement_number
        for row in rows
        if getattr(row, "power_measurement_status", None) == "failed"
    }
    invalid_power_measurements = {
        getattr(row, "power_measurement_id", None) or row.measurement_number
        for row in rows
        if getattr(row, "power_measurement_status", None) == "invalid"
    }
    partial_power_measurements = {
        getattr(row, "power_measurement_id", None) or row.measurement_number
        for row in rows
        if getattr(row, "power_measurement_status", None)
        == "measured_with_invalid_samples"
    }
    over_limit_power_measurements = {
        getattr(row, "power_measurement_id", None) or row.measurement_number
        for row in rows
        if getattr(row, "power_measurement_status", None) == "over_limit"
    }
    unsafe_status_power_measurements = {
        getattr(row, "power_measurement_id", None) or row.measurement_number
        for row in rows
        if getattr(row, "power_measurement_status", None)
        == "unsafe_meter_status"
    }
    nonpositive_power_measurements = {
        getattr(row, "power_measurement_id", None) or row.measurement_number
        for row in rows
        if row.power_mw is not None and row.power_mw <= 0
    }

    linked_power_attempt_ids = {
        str(getattr(row, "power_measurement_id"))
        for row in rows
        if getattr(row, "power_measurement_id", None) is not None
    }
    indexed_attempt_ids: set[str] = set()
    attempt_ids_by_status: dict[str, set[str]] = {}
    for index, attempt in enumerate(attempts, start=1):
        if isinstance(attempt, dict):
            attempt_id = attempt.get("attempt_id")
            status = attempt.get("status")
        else:
            attempt_id = getattr(attempt, "attempt_id", None)
            status = getattr(attempt, "status", None)
        stable_id = (
            str(attempt_id).strip()
            if attempt_id is not None and str(attempt_id).strip()
            else f"unidentified_attempt_{index}"
        )
        indexed_attempt_ids.add(stable_id)
        if status is not None:
            attempt_ids_by_status.setdefault(str(status), set()).add(stable_id)

    failed_power_measurements.update(attempt_ids_by_status.get("failed", set()))
    invalid_power_measurements.update(attempt_ids_by_status.get("invalid", set()))
    partial_power_measurements.update(
        attempt_ids_by_status.get("measured_with_invalid_samples", set())
    )
    over_limit_power_measurements.update(
        attempt_ids_by_status.get("over_limit", set())
    )
    unsafe_status_power_measurements.update(
        attempt_ids_by_status.get("unsafe_meter_status", set())
    )
    attempts_without_spectra = indexed_attempt_ids - linked_power_attempt_ids

    return {
        "measurement_count": len(measurement_numbers),
        "harmonic_row_count": len(rows),
        "saturated_measurement_count": len(saturated_measurements),
        "window_saturated_row_count": sum(row.window_saturated for row in rows),
        "negative_final_signal_row_count": sum(
            row.integrated_signal < 0 for row in rows
        ),
        "target_power_row_count": len(target_power_rows),
        "achieved_power_row_count": sum(row.power_mw is not None for row in rows),
        "power_rms_row_count": sum(
            getattr(row, "power_rms_mw", None) is not None for row in rows
        ),
        "power_std_row_count": sum(
            getattr(row, "power_std_mw", None) is not None for row in rows
        ),
        "power_duration_row_count": sum(
            getattr(row, "power_measurement_duration_s", None) is not None
            for row in rows
        ),
        "target_power_with_achieved_count": sum(
            row.power_mw is not None for row in target_power_rows
        ),
        "target_power_with_rms_count": sum(
            getattr(row, "power_rms_mw", None) is not None
            for row in target_power_rows
        ),
        "target_power_with_std_count": sum(
            getattr(row, "power_std_mw", None) is not None
            for row in target_power_rows
        ),
        "target_power_with_duration_count": sum(
            getattr(row, "power_measurement_duration_s", None) is not None
            for row in target_power_rows
        ),
        "failed_power_measurement_count": len(failed_power_measurements),
        "invalid_power_measurement_count": len(invalid_power_measurements),
        "partial_power_measurement_count": len(partial_power_measurements),
        "over_limit_power_measurement_count": len(
            over_limit_power_measurements
        ),
        "unsafe_status_power_measurement_count": len(
            unsafe_status_power_measurements
        ),
        "nonpositive_power_measurement_count": len(
            nonpositive_power_measurements
        ),
        "power_attempt_count": len(indexed_attempt_ids),
        "power_attempt_without_spectrum_count": len(attempts_without_spectra),
    }


def build_analysis_warnings(
    *,
    results: Iterable[HarmonicResult],
    background_mode: str,
    available_backgrounds: Iterable[str],
    transmission_mode: str,
    experimental_metadata: dict,
    power_attempts: Iterable[object] = (),
) -> list[dict[str, str]]:
    """Build warnings for omitted choices and notable data-quality flags."""

    rows = tuple(results)
    quality = build_quality_summary(rows, power_attempts=power_attempts)
    warnings: list[AnalysisWarning] = []
    available_backgrounds = list(available_backgrounds)
    filters = installed_filter_names(experimental_metadata)

    if background_mode == BACKGROUND_NOT_SPECIFIED and available_backgrounds:
        warnings.append(
            AnalysisWarning(
                code="background_choice_unspecified",
                message=(
                    "Saved background data are available but background "
                    "subtraction was not selected. Available: "
                    + ", ".join(available_backgrounds)
                    + ". Use --use-background or --no-background explicitly."
                ),
            )
        )

    if transmission_mode == TRANSMISSION_NOT_SPECIFIED and filters:
        warnings.append(
            AnalysisWarning(
                code="installed_filter_without_transmission_choice",
                message=(
                    "Installed filter metadata are present but no transmission "
                    "correction choice was made. Filters: "
                    + ", ".join(filters)
                    + ". Supply a correction or use "
                    "--no-transmission-correction explicitly."
                ),
            )
        )

    if transmission_mode in {TRANSMISSION_SCALAR, TRANSMISSION_CURVE} and not filters:
        warnings.append(
            AnalysisWarning(
                code="transmission_correction_without_filter_metadata",
                message=(
                    "A transmission correction was applied, but the experiment "
                    "metadata do not identify an installed filter."
                ),
            )
        )

    if quality["saturated_measurement_count"]:
        warnings.append(
            AnalysisWarning(
                code="saturated_measurements",
                message=(
                    f"{quality['saturated_measurement_count']} measurement(s) "
                    "were globally saturated in the raw detector data."
                ),
            )
        )

    if quality["window_saturated_row_count"]:
        warnings.append(
            AnalysisWarning(
                code="saturated_harmonic_windows",
                message=(
                    f"{quality['window_saturated_row_count']} harmonic row(s) "
                    "contain saturation inside the integration window."
                ),
            )
        )

    if quality["negative_final_signal_row_count"]:
        warnings.append(
            AnalysisWarning(
                code="negative_corrected_signals",
                message=(
                    f"{quality['negative_final_signal_row_count']} final "
                    "integrated signal row(s) are negative. Values were "
                    "preserved rather than clipped."
                ),
            )
        )

    if quality["failed_power_measurement_count"]:
        warnings.append(
            AnalysisWarning(
                code="failed_power_measurements",
                message=(
                    f"{quality['failed_power_measurement_count']} incident-"
                    "power measurement(s) failed. Their achieved power is "
                    "left missing; no value was predicted or substituted."
                ),
            )
        )

    if quality["invalid_power_measurement_count"]:
        warnings.append(
            AnalysisWarning(
                code="invalid_power_measurements",
                message=(
                    f"{quality['invalid_power_measurement_count']} incident-"
                    "power trace(s) contained no valid positive reading. "
                    "Zero, negative, missing, and status-flagged raw samples "
                    "are preserved, but no achieved power was inferred."
                ),
            )
        )

    if quality["partial_power_measurement_count"]:
        warnings.append(
            AnalysisWarning(
                code="partially_invalid_power_measurements",
                message=(
                    f"{quality['partial_power_measurement_count']} incident-"
                    "power trace(s) included invalid raw samples. They were "
                    "preserved but excluded from the reported mean, "
                    "standard deviation, and RMS."
                ),
            )
        )

    if quality["over_limit_power_measurement_count"]:
        warnings.append(
            AnalysisWarning(
                code="incident_power_over_limit",
                message=(
                    f"{quality['over_limit_power_measurement_count']} incident-"
                    "power attempt(s) exceeded the configured safety limit."
                ),
            )
        )

    if quality["unsafe_status_power_measurement_count"]:
        warnings.append(
            AnalysisWarning(
                code="unsafe_power_meter_status",
                message=(
                    f"{quality['unsafe_status_power_measurement_count']} "
                    "incident-power attempt(s) contained an unsafe meter "
                    "status/non-finite flag."
                ),
            )
        )

    if quality["power_attempt_without_spectrum_count"]:
        warnings.append(
            AnalysisWarning(
                code="power_attempts_without_spectra",
                message=(
                    f"{quality['power_attempt_without_spectrum_count']} saved "
                    "incident-power attempt(s) have no associated spectrum. "
                    "This records an acquisition abort or a later spectrum "
                    "failure; inspect power_attempts.json for the exact status "
                    "and error."
                ),
            )
        )

    if quality["nonpositive_power_measurement_count"]:
        warnings.append(
            AnalysisWarning(
                code="nonpositive_achieved_power",
                message=(
                    f"{quality['nonpositive_power_measurement_count']} "
                    "measurement(s) contain a legacy non-positive achieved "
                    "power value. Treat these as invalid; the analysis does "
                    "not replace them."
                ),
            )
        )

    target_count = quality["target_power_row_count"]
    if target_count:
        if target_count < quality["harmonic_row_count"]:
            warnings.append(
                AnalysisWarning(
                    code="partial_target_power_coverage",
                    message=(
                        "Target power is recorded for only part of the "
                        "analysed dataset. Automatic rotation centres will "
                        "use achieved powers instead of incomplete targets."
                    ),
                )
            )
        incomplete = []
        if quality["target_power_with_achieved_count"] < target_count:
            incomplete.append("achieved mean power")
        if quality["target_power_with_rms_count"] < target_count:
            incomplete.append("power RMS")
        if quality["target_power_with_std_count"] < target_count:
            incomplete.append("power population standard deviation")
        if quality["target_power_with_duration_count"] < target_count:
            incomplete.append("power measurement duration")
        if incomplete:
            warnings.append(
                AnalysisWarning(
                    code="incomplete_power_statistics",
                    message=(
                        "Target power is recorded, but some measurement rows "
                        "lack " + ", ".join(incomplete) + "."
                    ),
                )
            )

    return [warning.as_dict() for warning in warnings]


def correction_annotation(recipe: dict) -> str:
    """Return a concise correction label suitable for quick-look figures."""

    background = recipe.get("background", {})
    transmission = recipe.get("transmission_correction", {})
    metadata = recipe.get("experimental_metadata", {})
    filters = installed_filter_names(metadata) if isinstance(metadata, dict) else []
    filter_suffix = f" [{', '.join(filters)}]" if filters else ""

    if background.get("mode") == BACKGROUND_USED:
        background_text = f"Background: {background.get('name', 'used')}"
    else:
        background_text = "Background: NOT USED"

    transmission_mode = transmission.get("mode")
    if transmission_mode == TRANSMISSION_SCALAR:
        transmission_text = (
            "Transmission: fraction "
            f"{transmission.get('fraction', 'unknown')}{filter_suffix}"
        )
    elif transmission_mode == TRANSMISSION_CURVE:
        source = transmission.get("source_file")
        transmission_text = (
            f"Transmission: {Path(source).name}{filter_suffix}"
            if source
            else f"Transmission: curve{filter_suffix}"
        )
    else:
        transmission_text = f"Transmission: NOT USED{filter_suffix}"

    signal = recipe.get("plot_signal", "integrated_signal")
    if signal in {"raw_integrated_signal", "raw_peak_signal"}:
        display_text = f"Displayed: {signal} (raw; corrections not applied)"
    elif signal == "background_corrected_integral":
        display_text = (
            "Displayed: background_corrected_integral "
            "(transmission correction not applied)"
        )
    else:
        display_text = f"Displayed: {signal} (selected corrections applied)"

    return f"{display_text} | {background_text} | {transmission_text}"


def render_console_summary(recipe: dict) -> str:
    """Render the most important correction choices and warnings for a CLI."""

    background = recipe.get("background", {})
    transmission = recipe.get("transmission_correction", {})
    coordinate = recipe.get("input_coordinate", "")
    coordinate_unit = {
        "waveplate_angle_deg": "deg",
        "power_mw": "mW",
        "fluence_mj_cm2": "mJ/cm^2",
        "intensity_w_cm2": "W/cm^2",
    }.get(coordinate, "")
    tolerance = f"{recipe.get('input_tolerance', 0):g}"
    if coordinate_unit:
        tolerance = f"{tolerance} {coordinate_unit}"
    lines = [
        "",
        "Analysis performed",
        "------------------",
        f"Background subtraction : {_background_description(background)}",
        f"Transmission correction: {_transmission_description(transmission)}",
        (
            "Final plotted signal    : "
            + _signal_description(recipe.get("plot_signal", ""))
        ),
        f"Input coordinate        : {coordinate}",
        f"Fixed-value tolerance   : ± {tolerance}",
    ]
    warnings = recipe.get("warnings", [])
    if warnings:
        lines.extend(["", "Warnings"])
        for warning in warnings:
            lines.append(f"  WARNING: {warning.get('message', warning)}")
    else:
        lines.extend(["", "Warnings: none"])
    return "\n".join(lines)


def render_analysis_summary(
    recipe: dict,
    *,
    recipe_sha256: str,
) -> str:
    """Render a durable Markdown account of an analysis run."""

    metadata = recipe.get("experimental_metadata", {})
    if not isinstance(metadata, dict):
        metadata = {}
    harmonics = recipe.get("harmonics", [])
    background = recipe.get("background", {})
    transmission = recipe.get("transmission_correction", {})
    quality = recipe.get("quality_summary", {})
    figures = recipe.get("figures", [])
    filters = installed_filter_names(metadata)
    warnings = recipe.get("warnings", [])

    lines = [
        "# Harmonic analysis summary",
        "",
        f"- Analysis ID: `{recipe.get('analysis_id', '')}`",
        f"- Created: `{recipe.get('created', '')}`",
        f"- Source experiment: `{recipe.get('source_experiment', '')}`",
        f"- Source run ID: `{recipe.get('source_run_id', '')}`",
        f"- Analysis recipe SHA-256: `{recipe_sha256}`",
        "",
        "## Experimental context",
        "",
        f"- Run label: {_text_or_not_recorded(metadata.get('run_label'))}",
        f"- Sample: {_text_or_not_recorded(metadata.get('sample_name'))}",
        f"- Notes: {_text_or_not_recorded(metadata.get('notes'))}",
        (
            "- Installed filters: "
            + (", ".join(filters) if filters else "not recorded")
        ),
        "",
        "## Harmonic integration",
        "",
        "| Harmonic | Minimum (nm) | Maximum (nm) |",
        "|---|---:|---:|",
    ]
    for harmonic in harmonics:
        lines.append(
            f"| {harmonic.get('name', '')} | "
            f"{harmonic.get('wavelength_min_nm', '')} | "
            f"{harmonic.get('wavelength_max_nm', '')} |"
        )

    lines.extend(
        [
            "",
            "## Corrections",
            "",
            f"- Background subtraction: {_background_description(background)}",
            (
                "- Transmission correction: "
                + _transmission_description(transmission)
            ),
            (
                "- Final plotted signal: "
                + _signal_description(recipe.get("plot_signal", ""))
            ),
            f"- Integration algorithm: `{recipe.get('integration', '')}`",
            "- Correction pipeline:",
        ]
    )
    for step in recipe.get("correction_pipeline", []):
        lines.append(
            f"  {step.get('order', '')}. {step.get('name', '')}: "
            f"{step.get('mode', '')}"
        )
    if background.get("mode") == BACKGROUND_USED:
        lines.extend(
            [
                (
                    "- Background timestamp: `"
                    f"{background.get('spectrum_timestamp', '')}`"
                ),
                f"- Background source: `{background.get('source_file', '')}`",
                (
                    "- Background SHA-256: `"
                    f"{background.get('source_sha256', '')}`"
                ),
            ]
        )
    elif background.get("available_backgrounds"):
        lines.append(
            "- Available saved backgrounds: "
            + ", ".join(background["available_backgrounds"])
        )
    if transmission.get("applied"):
        lines.append(
            "- Minimum accepted transmission fraction: `"
            f"{transmission.get('minimum_fraction', '')}`"
        )
        if transmission.get("source_file"):
            lines.extend(
                [
                    (
                        "- Transmission source: `"
                        f"{transmission.get('source_file', '')}`"
                    ),
                    (
                        "- Transmission SHA-256: `"
                        f"{transmission.get('source_sha256', '')}`"
                    ),
                ]
            )

    coordinate = recipe.get("input_coordinate", "")
    coordinate_description = (
        "achieved mean power (`power_mw`)" if coordinate == "power_mw" else coordinate
    )
    rotation_centres = recipe.get("rotation_centres", {})
    lines.extend(
        [
            "",
            "## Selection and plotting",
            "",
            f"- Input coordinate: {coordinate_description}",
            (
                "- Fixed-value absolute tolerance: ± "
                f"{recipe.get('input_tolerance', 0)}"
            ),
            (
                "- Rotation centres (all): `"
                f"{rotation_centres.get('values', [])}`"
            ),
            (
                "- Explicit rotation centres: `"
                f"{rotation_centres.get('explicit_values', [])}`"
            ),
            (
                "- Automatic rotation centres: `"
                f"{rotation_centres.get('automatic_values', [])}` from "
                f"`{rotation_centres.get('automatic_source') or 'none'}`"
            ),
            f"- Plot normalisation: `{recipe.get('normalise_plots', False)}`",
            (
                "- Quick-look correction annotation: `"
                f"{recipe.get('annotate_corrections', False)}`"
            ),
            "- Replicates: preserved as individual rows; not averaged",
            (
                "- Power fields: `target_power_mw` is the requested setpoint; "
                "`power_mw` is the arithmetic mean of valid positive raw "
                "samples; `power_std_mw` is their population standard "
                "deviation; `power_rms_mw` is sqrt(mean(power^2)); no "
                "missing or invalid power is predicted"
            ),
            "",
            "## Quality summary",
            "",
            f"- Measurements: {quality.get('measurement_count', 0)}",
            f"- Harmonic rows: {quality.get('harmonic_row_count', 0)}",
            (
                "- Globally saturated measurements: "
                f"{quality.get('saturated_measurement_count', 0)}"
            ),
            (
                "- Saturated harmonic rows: "
                f"{quality.get('window_saturated_row_count', 0)}"
            ),
            (
                "- Negative final signal rows: "
                f"{quality.get('negative_final_signal_row_count', 0)}"
            ),
            (
                "- Rows with target / achieved / STD / RMS / duration power "
                "data: "
                f"{quality.get('target_power_row_count', 0)} / "
                f"{quality.get('achieved_power_row_count', 0)} / "
                f"{quality.get('power_std_row_count', 0)} / "
                f"{quality.get('power_rms_row_count', 0)} / "
                f"{quality.get('power_duration_row_count', 0)}"
            ),
            (
                "- Failed / invalid / partially-invalid incident-power "
                "measurements: "
                f"{quality.get('failed_power_measurement_count', 0)} / "
                f"{quality.get('invalid_power_measurement_count', 0)} / "
                f"{quality.get('partial_power_measurement_count', 0)}"
            ),
            (
                "- Over-limit / unsafe-status incident-power attempts: "
                f"{quality.get('over_limit_power_measurement_count', 0)} / "
                f"{quality.get('unsafe_status_power_measurement_count', 0)}"
            ),
            (
                "- Saved power attempts / attempts without spectra: "
                f"{quality.get('power_attempt_count', 0)} / "
                f"{quality.get('power_attempt_without_spectrum_count', 0)}"
            ),
            "",
            "## Warnings",
            "",
        ]
    )
    if warnings:
        for warning in warnings:
            lines.append(
                f"- **{warning.get('code', 'warning')}**: "
                f"{warning.get('message', warning)}"
            )
    else:
        lines.append("- None.")

    lines.extend(
        [
            "",
            "## Outputs",
            "",
            "- Master harmonic table: `harmonic_signals.csv`",
            (
                "- Master table SHA-256: `"
                f"{recipe.get('checksums', {}).get('harmonic_signals.csv', '')}`"
            ),
            "- Machine-readable recipe: `analysis_recipe.json`",
            "- Recipe checksum: `analysis_recipe.sha256`",
            "- Human-readable summary: `analysis_summary.md`",
            "",
            (
                "| Plot type | Fixed selection | Tolerance | Matched range | "
                "Rows | PNG | PDF | Data file |"
            ),
            "|---|---|---:|---|---:|---|---|---|",
        ]
    )
    for figure in figures:
        fixed_unit = figure.get("fixed_unit", "")
        unit_suffix = f" {fixed_unit}" if fixed_unit else ""
        pdf_file = figure.get("pdf_file") or ""
        fixed_selection = (
            f"{figure.get('fixed_field', '')}="
            f"{figure.get('fixed_value', '')}{unit_suffix}"
        )
        matched_range = (
            f"{figure.get('matched_fixed_min', '')} to "
            f"{figure.get('matched_fixed_max', '')}{unit_suffix}"
        )
        lines.append(
            f"| {figure.get('plot_type', '')} | {fixed_selection} | "
            f"{figure.get('fixed_tolerance', '')}{unit_suffix} | "
            f"{matched_range} | "
            f"{figure.get('row_count', '')} | "
            f"`{figure.get('png_file', '')}` | "
            f"`{pdf_file}` | "
            f"`{figure.get('data_file', '')}` |"
        )

    software = recipe.get("software", {})
    lines.extend(
        [
            "",
            "## Software",
            "",
            f"- Application: `{software.get('application', '')}`",
            f"- Entry point: `{software.get('entry_point', '')}`",
            f"- Python: `{software.get('python', '')}`",
            f"- NumPy: `{software.get('numpy', '')}`",
            f"- Matplotlib: `{software.get('matplotlib', '')}`",
            "",
        ]
    )
    return "\n".join(lines)


def _background_description(background: dict) -> str:
    mode = background.get("mode")
    if mode == BACKGROUND_USED:
        return f"USED - {background.get('name', 'unnamed')}"
    if mode == BACKGROUND_EXPLICITLY_NOT_USED:
        return "NOT USED (explicit choice)"
    return "NOT USED (no explicit choice supplied)"


def _transmission_description(transmission: dict) -> str:
    mode = transmission.get("mode")
    if mode == TRANSMISSION_SCALAR:
        return f"USED - scalar fraction {transmission.get('fraction', '')}"
    if mode == TRANSMISSION_CURVE:
        source = transmission.get("source_file")
        return f"USED - curve {Path(source).name if source else ''}"
    if mode == TRANSMISSION_EXPLICITLY_NOT_USED:
        return "NOT USED (explicit choice)"
    return "NOT USED (no explicit choice supplied)"


def _text_or_not_recorded(value) -> str:
    text = str(value).strip() if value is not None else ""
    return text or "not recorded"


def _signal_description(signal: str) -> str:
    descriptions = {
        "integrated_signal": (
            "`integrated_signal` (final integral after selected corrections)"
        ),
        "raw_integrated_signal": (
            "`raw_integrated_signal` (raw integral; corrections not applied)"
        ),
        "background_corrected_integral": (
            "`background_corrected_integral` (before transmission correction)"
        ),
        "peak_signal": "`peak_signal` (peak after selected corrections)",
        "raw_peak_signal": "`raw_peak_signal` (raw peak)",
    }
    return descriptions.get(signal, f"`{signal}`")
