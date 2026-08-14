import os


DEFAULT_TEST_DATABASE_URL = (
    "postgresql+asyncpg://issuepilot:issuepilot@localhost:54329/issuepilot_test"
)

# Test collection imports the application after this file, so the async engine
# is built against a database that cannot contain development acceptance tasks.
os.environ["DATABASE_URL"] = os.environ.get(
    "TEST_DATABASE_URL", DEFAULT_TEST_DATABASE_URL
)
