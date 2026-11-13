# Non-production identity fixtures smoke test and re-export
from tests.identity_fixtures import (
    TEST_RSA_PRIVATE_KEY_PEM,
    TEST_RSA_PUBLIC_KEY_PEM,
    TEST_TOKEN_ISSUER,
    TEST_TOKEN_AUDIENCE,
    issue_fixed_test_token,
    get_test_token,
    get_test_auth_headers,
)

def test_identity_fixtures_generate_valid_tokens():
    token = get_test_token('test-actor')
    assert token is not None
    assert len(token) > 20
