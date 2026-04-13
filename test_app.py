import unittest


def load_tests(loader: unittest.TestLoader, tests: unittest.TestSuite, pattern: str) -> unittest.TestSuite:
    # Delegate explicitly to app_test to avoid wildcard imports and keep discovery predictable.
    return loader.discover(".", pattern="app_test.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
