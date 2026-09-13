"""Root pytest configuration.

The shared fixtures live in tests/framework/fixtures.py so that every suite in this repo
(tests/ and harness/) gets them. Another project adopting the framework copies the
tests/framework package and adds this one line to its own root conftest.
"""

pytest_plugins = ["tests.framework.fixtures"]
