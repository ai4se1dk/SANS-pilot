"""Neutron SLD calculation, ported from SasView's SldPanel."""

from __future__ import annotations

from typing import cast

from periodictable.nsf import neutron_scattering

_SCALE = 1e-6

_NeutronSldTriplet = tuple[float, float, float]
_NeutronScatteringResult = tuple[
  _NeutronSldTriplet,
  _NeutronSldTriplet,
  float,
]


def calculate_neutron_sld(
  molecular_formula: str,
  mass_density: float | None = None,
  neutron_wavelength: float = 6.0,
) -> dict:
  """Calculate the Neutron Scattering Length Density for a compound.

  Args:
      molecular_formula: Chemical formula (e.g. ``"H2O"``, ``"D2O"``).
      mass_density: Mass density in g/cm³.  Required for simple formulas;
          may be omitted when all component densities are embedded in the
          formula via ``@density`` notation.
      neutron_wavelength: Neutron wavelength in Ångströms (default 6.0).

  Returns:
      Dictionary with SLD results and unit metadata.
  """
  if not molecular_formula or not molecular_formula.strip():
    raise ValueError("molecular_formula is required")
  if neutron_wavelength <= 0:
    raise ValueError("neutron_wavelength must be positive")
  if mass_density is not None and mass_density <= 0:
    raise ValueError("mass_density must be positive")

  scattering_kwargs: dict = {
    "compound": molecular_formula,
    "wavelength": neutron_wavelength,
  }
  if mass_density is not None:
    scattering_kwargs["density"] = mass_density

  try:
    scattering_result = neutron_scattering(**scattering_kwargs)
    if any(part is None for part in scattering_result):
      raise ValueError(
        f"Could not calculate neutron scattering for '{molecular_formula}'"
      )

    (
      (neutron_sld_real, neutron_sld_imag, _),
      (_, _neutron_abs_xs, _neutron_inc_xs),
      _neutron_length,
    ) = cast(_NeutronScatteringResult, scattering_result)
  except KeyError as exc:
    raise ValueError(
      f"Unknown element or invalid formula: {molecular_formula}"
    ) from exc
  except Exception as exc:
    # periodictable raises ValueError or pyparsing.exceptions.ParseException
    raise ValueError(
      f"Could not parse molecular formula '{molecular_formula}': {exc}"
    ) from exc

  return {
    "molecular_formula": molecular_formula,
    "mass_density": mass_density,
    "neutron_wavelength": neutron_wavelength,
    "neutron_sld_real": _SCALE * neutron_sld_real,
    "neutron_sld_imag": _SCALE * abs(neutron_sld_imag),
    "units": {
      "neutron_sld": "Å⁻²",
      "wavelength": "Å",
      "density": "g/cm³",
    },
  }
