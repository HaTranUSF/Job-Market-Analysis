import unittest

from ats_sources import STATE_CODES
from transform.locations import enrich_locations, resolve


class LocationTests(unittest.TestCase):
    def test_city_lookup_and_explicit_formats(self):
        for value, expected in (("Boston", "Massachusetts"), ("Mountain View", "California"),
                                ("San Francisco Bay Area", "California"), ("New York Office", "New York"),
                                ("Massachusetts - Boston", "Massachusetts"), ("Cambridge, MA USA", "Massachusetts"),
                                ("Atlanta, GA (Open Remote - Eastern Time Zone)", "Georgia"),
                                ("Washington, D.C.", "District of Columbia")):
            with self.subTest(value=value):
                self.assertEqual(resolve(dict(location=value, country="US"), STATE_CODES)[1], expected)

    def test_washington_state_and_state_prefix(self):
        for value, expected in (("Seattle, Washington, United States", "Washington"),
                                ("Kirkland, Washington", "Washington"),
                                ("North Carolina-Remote, United States", "North Carolina"),
                                ("New York, United States", "New York")):
            self.assertEqual(resolve(dict(location=value, country="US"), STATE_CODES)[1], expected)

    def test_unknown_and_foreign_locations_are_not_guessed(self):
        for value in ("United States", "US - Remote", "Remote", "Springfield", "Portland", "Washington"):
            self.assertIsNone(resolve(dict(location=value, country="US"), STATE_CODES)[1])
        self.assertIsNone(resolve(dict(location="Cambridge", country="GB"), STATE_CODES)[1])

    def test_multiple_locations_and_inference_provenance(self):
        locations = enrich_locations([dict(location="San Francisco or Denver", country="US")], STATE_CODES)
        self.assertEqual({loc["state"] for loc in locations}, {"California", "Colorado"})
        self.assertTrue(all(loc["state_source"] == "city_lookup" for loc in locations))
