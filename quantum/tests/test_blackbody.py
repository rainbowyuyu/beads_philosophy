import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("blackbody", Path(__file__).resolve().parents[1] / "blackbody.py")
blackbody = importlib.util.module_from_spec(spec)
spec.loader.exec_module(blackbody)


class BlackbodyTests(unittest.TestCase):
    def test_peak_matches_wien_law(self):
        for temperature in (3000, 4500, 6000):
            peak = blackbody.WIEN / temperature * 1e6
            center = blackbody.radiance_per_um(peak, temperature)
            self.assertGreater(center, blackbody.radiance_per_um(peak * .99, temperature))
            self.assertGreater(center, blackbody.radiance_per_um(peak * 1.01, temperature))

    def test_shared_scale_and_units(self):
        self.assertAlmostEqual(blackbody.radiance_per_um(.5, 6000), 31756906.656, delta=2)
        self.assertGreater(blackbody.radiance_per_um(.8, 6000), blackbody.radiance_per_um(.8, 3000))

    def test_stefan_boltzmann_integral(self):
        # A log-spaced numerical integration tests the wavelength unit conversion.
        import math
        temperature = 4500
        wavelengths = [10 ** (-3 + i * 6 / 12000) for i in range(12001)]
        vals = [blackbody.radiance_per_um(w, temperature) for w in wavelengths]
        integral = sum((b-a) * (fa+fb) / 2 for a,b,fa,fb in zip(wavelengths, wavelengths[1:], vals, vals[1:]))
        target = 5.670374419e-8 * temperature**4
        self.assertAlmostEqual(math.pi * integral / target, 1.0, delta=2e-5)

    def test_reject_invalid_units(self):
        for wavelength, temp in [(0, 3000), (-1, 3000), (1, 0), (float('nan'), 3000)]:
            with self.assertRaises(ValueError):
                blackbody.radiance_per_um(wavelength, temp)


if __name__ == "__main__":
    unittest.main()
