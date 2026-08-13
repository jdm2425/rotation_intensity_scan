"""Hardware-free argument tests for the standalone power-probe diagnostic."""

from __future__ import annotations

from tools.test_power_probe_hardware import build_parser, _validate_arguments


def test_measure_defaults_to_auto_range_without_abort_threshold() -> None:
    arguments = build_parser().parse_args(["measure", "--traces", "3"])
    _validate_arguments(arguments)
    assert arguments.range_option == "AUTO"
    assert arguments.maximum_power_mw is None
    assert arguments.abort_above_maximum is False


def test_abort_requires_an_explicit_threshold() -> None:
    arguments = build_parser().parse_args(
        ["measure", "--abort-above-maximum"]
    )
    try:
        _validate_arguments(arguments)
    except ValueError as error:
        assert "requires --maximum-power-mw" in str(error)
    else:
        raise AssertionError("Expected missing diagnostic threshold to fail.")


if __name__ == "__main__":
    test_measure_defaults_to_auto_range_without_abort_threshold()
    test_abort_requires_an_explicit_threshold()
    print("POWER PROBE HARDWARE CLI TEST PASSED")
