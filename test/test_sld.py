"""Tests for the SLD calculation module."""

from __future__ import annotations

import pytest

from sans_pilot.sld import calculate_neutron_sld

# ---------------------------------------------------------------------------
# Happy-path calculations (values cross-checked against SasView)
# ---------------------------------------------------------------------------


class TestWater:
  def test_sld_real(self):
    result = calculate_neutron_sld("H2O", mass_density=1.0, neutron_wavelength=6.0)
    assert result["neutron_sld_real"] == pytest.approx(-5.6e-7, abs=1e-8)

  def test_sld_imag_positive(self):
    result = calculate_neutron_sld("H2O", mass_density=1.0, neutron_wavelength=6.0)
    assert result["neutron_sld_imag"] > 0


class TestHeavyWater:
  def test_sld_real(self):
    result = calculate_neutron_sld("D2O", mass_density=1.107, neutron_wavelength=6.0)
    assert result["neutron_sld_real"] == pytest.approx(6.33e-6, abs=1e-7)


class TestSiliconDioxide:
  def test_sld_real(self):
    result = calculate_neutron_sld("SiO2", mass_density=2.2, neutron_wavelength=6.0)
    assert result["neutron_sld_real"] == pytest.approx(3.47e-6, abs=1e-7)


class TestCustomWavelength:
  def test_custom_wavelength_returns_valid_result(self):
    # periodictable SLD values are wavelength-independent; wavelength only
    # affects cross-sections (not returned by this tool).  Verify the tool
    # accepts a non-default wavelength and produces consistent SLD values.
    result = calculate_neutron_sld("H2O", mass_density=1.0, neutron_wavelength=1.8)
    assert result["neutron_wavelength"] == 1.8
    assert result["neutron_sld_real"] == pytest.approx(-5.6e-7, abs=1e-8)
    assert result["neutron_sld_imag"] > 0


class TestEmbeddedDensityMixture:
  def test_no_external_density_required(self):
    result = calculate_neutron_sld(
      "50%vol H2O@1.0 // 50%vol D2O@1.107",
      neutron_wavelength=6.0,
    )
    # Should return a result between pure H2O and pure D2O
    assert result["neutron_sld_real"] > -5.6e-7
    assert result["neutron_sld_real"] < 6.33e-6
    assert result["mass_density"] is None


# ---------------------------------------------------------------------------
# Output shape
# ---------------------------------------------------------------------------


class TestOutputShape:
  def test_keys(self):
    result = calculate_neutron_sld("H2O", mass_density=1.0)
    expected_keys = {
      "molecular_formula",
      "mass_density",
      "neutron_wavelength",
      "neutron_sld_real",
      "neutron_sld_imag",
      "units",
    }
    assert set(result.keys()) == expected_keys

  def test_units(self):
    result = calculate_neutron_sld("H2O", mass_density=1.0)
    assert result["units"]["neutron_sld"] == "Å⁻²"
    assert result["units"]["wavelength"] == "Å"
    assert result["units"]["density"] == "g/cm³"

  def test_echoes_inputs(self):
    result = calculate_neutron_sld("SiO2", mass_density=2.2, neutron_wavelength=1.8)
    assert result["molecular_formula"] == "SiO2"
    assert result["mass_density"] == 2.2
    assert result["neutron_wavelength"] == 1.8


# ---------------------------------------------------------------------------
# Validation / error paths
# ---------------------------------------------------------------------------


class TestValidation:
  def test_empty_formula_raises(self):
    with pytest.raises(ValueError, match="molecular_formula is required"):
      calculate_neutron_sld("", mass_density=1.0)

  def test_whitespace_formula_raises(self):
    with pytest.raises(ValueError, match="molecular_formula is required"):
      calculate_neutron_sld("   ", mass_density=1.0)

  def test_invalid_formula_raises(self):
    with pytest.raises(ValueError):
      calculate_neutron_sld("Zq3", mass_density=1.0)

  def test_negative_density_raises(self):
    with pytest.raises(ValueError, match="mass_density must be positive"):
      calculate_neutron_sld("H2O", mass_density=-1.0)

  def test_zero_wavelength_raises(self):
    with pytest.raises(ValueError, match="neutron_wavelength must be positive"):
      calculate_neutron_sld("H2O", mass_density=1.0, neutron_wavelength=0.0)

  def test_negative_wavelength_raises(self):
    with pytest.raises(ValueError, match="neutron_wavelength must be positive"):
      calculate_neutron_sld("H2O", mass_density=1.0, neutron_wavelength=-1.0)


# ---------------------------------------------------------------------------
# MCP tool-level integration test
# ---------------------------------------------------------------------------


class TestMCPToolRegistration:
  def test_calculate_sld_tool_exists(self):
    """Verify the tool is registered on the MCP server."""
    import asyncio

    from sans_pilot.main import mcp

    tools = asyncio.run(mcp.list_tools())
    tool_names = [t.name for t in tools]
    assert "calculate-sld" in tool_names

  def test_invalid_input_returns_mcp_error(self):
    """Calling the tool with an invalid formula should raise a ToolError
    so the MCP protocol can return a structured error to the client."""
    import asyncio

    from fastmcp.exceptions import ToolError

    from sans_pilot.main import mcp

    with pytest.raises(ToolError, match="Could not parse"):
      asyncio.run(
        mcp.call_tool(
          "calculate-sld", {"molecular_formula": "Zq3", "mass_density": 1.0}
        )
      )
