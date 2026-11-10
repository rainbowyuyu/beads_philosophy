"""Plot Planck's wavelength spectral radiance without a plotting dependency."""
from __future__ import annotations

import argparse
import csv
import json
import math
from pathlib import Path

H = 6.62607015e-34
C = 299792458.0
K_B = 1.380649e-23
WIEN = 2.897771955e-3  # wavelength peak, m K


def radiance_per_um(wavelength_um: float, temperature_k: float) -> float:
    """W / (m² sr µm); both inputs must be finite and positive."""
    if not (math.isfinite(wavelength_um) and wavelength_um > 0
            and math.isfinite(temperature_k) and temperature_k > 0):
        raise ValueError("Wavelength and temperature must be positive finite numbers")
    wavelength_m = wavelength_um * 1e-6
    exponent = H * C / (wavelength_m * K_B * temperature_k)
    if exponent > 700:
        return 0.0
    return (2 * H * C * C / wavelength_m**5) / math.expm1(exponent) * 1e-6


def render(out: Path) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    temperatures = (3000, 4500, 6000)
    colors = ("#ffb66e", "#7bd9cf", "#c2b5ff")
    wavelengths = [.15 + i * (3.85 / 1200) for i in range(1201)]
    curves = [[radiance_per_um(w, t) for w in wavelengths] for t in temperatures]
    ymax = max(max(curve) for curve in curves) * 1.10
    x = lambda w: 112 + (w - .15) / 3.85 * 950
    y = lambda r: 590 - r / ymax * 420
    svg = ['<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720" role="img" aria-labelledby="title desc">',
           '<title id="title">Blackbody spectra at three temperatures</title>',
           '<desc id="desc">Planck law versus wavelength, using one shared vertical scale. Hotter objects have brighter curves and peaks at shorter wavelengths.</desc>',
           '<rect width="1200" height="720" rx="24" fill="#111c29"/>',
           '<g font-family="Arial, sans-serif" fill="#eef1f6">',
           '<text x="86" y="68" font-size="31">Light carries a thermometer.</text>',
           '<text x="86" y="105" font-size="18" fill="#b6c3cf">Planck law · calculated curves · one shared intensity scale</text>',
           '<text x="112" y="145" font-size="16" fill="#b6c3cf">Spectral radiance / MW m⁻² sr⁻¹ µm⁻¹</text>']
    for i in range(5):
        val = ymax * i / 4
        yy = y(val)
        svg.extend([f'<path d="M112 {yy:.3f}H1062" stroke="#334252"/>',
                    f'<text x="99" y="{yy+6:.3f}" text-anchor="end" font-size="16">{val/1e6:.1f}</text>'])
    for w in (.5, 1, 1.5, 2, 2.5, 3, 3.5, 4):
        xx = x(w)
        svg.append(f'<text x="{xx:.3f}" y="619" text-anchor="middle" font-size="16">{w:g}</text>')
    svg.append('<text x="1062" y="659" text-anchor="end" font-size="19">Wavelength / µm</text>')
    peaks = []
    for j, (temp, color, curve) in enumerate(zip(temperatures, colors, curves)):
        path = " ".join(("M" if i == 0 else "L") + f"{x(w):.3f},{y(r):.3f}"
                        for i, (w, r) in enumerate(zip(wavelengths, curve)))
        peak = WIEN / temp * 1e6
        svg.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="3.5"/>')
        svg.append(f'<text x="780" y="{204+j*37}" font-size="20" fill="{color}">{temp} K · peak {peak:.3f} µm</text>')
        peaks.append({"temperature_k": temp, "wien_peak_um": peak})
    svg.extend(['<text x="86" y="696" font-size="14" fill="#b6c3cf">beads_philosophy / rainbow鱼 — theoretical spectrum, not measured data</text>', '</g></svg>'])
    (out / "blackbody.svg").write_text("\n".join(svg), encoding="utf-8")
    with (out / "blackbody.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["wavelength_um"] + [f"radiance_{t}K_W_m-2_sr-1_um-1" for t in temperatures])
        writer.writerows(zip(wavelengths, *curves))
    summary = {"model": "Planck wavelength spectral radiance", "experimental": False,
               "wavelength_unit": "um", "radiance_unit": "W m^-2 sr^-1 um^-1",
               "shared_vertical_scale": True, "peaks": peaks,
               "constants_SI": {"h": H, "c": C, "k_B": K_B}}
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("outputs/quantum"))
    print(json.dumps(render(parser.parse_args().out), indent=2))
