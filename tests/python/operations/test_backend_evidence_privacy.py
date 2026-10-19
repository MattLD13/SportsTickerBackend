"""Keep plaintext server evidence out of public workflow artifacts."""
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives.asymmetric import rsa

pytestmark = pytest.mark.critical


def test_workflows_upload_only_encrypted_backend_evidence():
    for name in ("deploy.yml", "backend-diagnostics.yml"):
        source = (Path(".github/workflows") / name).read_text()
        assert "openssl cms -encrypt -binary -aes-256-gcm" in source
        assert "path: backend-report.p7m" in source
        assert "path: backend-report.zip" not in source
        assert "rm -f backend-report.zip" in source
    certificate = x509.load_pem_x509_certificate(Path(".github/backend-diagnostics-recipient.pem").read_bytes())
    assert isinstance(certificate.public_key(), rsa.RSAPublicKey)
    assert certificate.public_key().key_size >= 3072
    assert "PRIVATE KEY" not in Path(".github/backend-diagnostics-recipient.pem").read_text()
