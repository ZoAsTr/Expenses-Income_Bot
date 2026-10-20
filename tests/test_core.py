import unittest

from database.models import Limit
from services.classifier import parse_amount


class ParseAmountTests(unittest.TestCase):
    def test_integer_amount(self):
        self.assertEqual(parse_amount("450 фастфуд"), 450.0)

    def test_decimal_comma(self):
        self.assertEqual(parse_amount("450,50 продукты"), 450.5)

    def test_spaces_in_thousands(self):
        self.assertEqual(parse_amount("1 200 руб"), 1200.0)

    def test_rejects_missing_or_non_positive_amount(self):
        self.assertIsNone(parse_amount(""))
        self.assertIsNone(parse_amount("кофе"))
        self.assertIsNone(parse_amount("0"))


class LimitModelTests(unittest.TestCase):
    def test_correct_python_attribute_and_legacy_db_column(self):
        self.assertTrue(hasattr(Limit, "max_amount"))
        self.assertFalse(hasattr(Limit, "max_ammount"))
        column = Limit.__table__.columns["max_ammount"]
        self.assertEqual(column.name, "max_ammount")


if __name__ == "__main__":
    unittest.main()
