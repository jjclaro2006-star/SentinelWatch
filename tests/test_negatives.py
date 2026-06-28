import unittest

from sentinelwatch.negatives import line_points


class NegativeHelpersTests(unittest.TestCase):
    def test_reads_multiline_points(self):
        points = line_points({"type": "MultiLineString", "coordinates": [[[1, 2], [3, 4]], [[5, 6]]]})
        self.assertEqual([(1.0, 2.0), (3.0, 4.0), (5.0, 6.0)], points)


if __name__ == "__main__":
    unittest.main()
