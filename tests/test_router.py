import unittest

from zte_traffic_alert.router import parse_byte_value


class ParseByteValueTest(unittest.TestCase):
    def test_integer_string(self):
        self.assertEqual(parse_byte_value("123"), 123)

    def test_gib_like_string(self):
        self.assertEqual(parse_byte_value("1 GB"), 1024**3)

    def test_mib_like_string(self):
        self.assertEqual(parse_byte_value("1.5 MB"), int(1.5 * 1024**2))


if __name__ == "__main__":
    unittest.main()

