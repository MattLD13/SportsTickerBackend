"""Check the trust data embedded in the physical Mini firmware."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

from tools.mini.generate_mini_trust import (
    BLOCKED_ROOT_COMMON_NAMES,
    TRUSTED_CA_ORGANIZATIONS,
    build_trust_store,
)


pytestmark = pytest.mark.critical
ROOT = Path(__file__).resolve().parents[3]
STORE = ROOT / "ticker-mini/certs/backend.pem"


def test_committed_trust_store_matches_metadata_and_authorities() -> None:
    pem = STORE.read_bytes()
    metadata = json.loads(STORE.with_suffix(".json").read_text(encoding="utf-8"))
    roots = x509.load_pem_x509_certificates(pem)
    assert len(roots) == metadata["certificates"]
    assert hashlib.sha256(pem).hexdigest() == metadata["store_sha256"]
    assert set(metadata["organizations"]) == TRUSTED_CA_ORGANIZATIONS
    organizations = {item.value for root in roots for item in root.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)}
    assert organizations == TRUSTED_CA_ORGANIZATIONS
    common_names = {item.value for root in roots for item in root.subject.get_attributes_for_oid(NameOID.COMMON_NAME)}
    assert not (common_names & BLOCKED_ROOT_COMMON_NAMES)
    subjects = [root.subject.public_bytes() for root in roots]
    assert subjects == sorted(subjects)
    assert len({root.fingerprint(hashes.SHA256()) for root in roots}) == len(roots)


def test_generator_keeps_selected_root_certificates_and_removes_other_authorities() -> None:
    roots = x509.load_pem_x509_certificates(STORE.read_bytes())[:2]
    source_roots = x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    other = next(root for root in source_roots if not any(
        item.value in TRUSTED_CA_ORGANIZATIONS
        for item in root.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME)
    ))
    source = b"".join(root.public_bytes(serialization.Encoding.PEM) for root in [*reversed(roots), other])
    actual = x509.load_pem_x509_certificates(build_trust_store(source))
    assert [root.public_bytes(serialization.Encoding.DER) for root in actual] == [
        root.public_bytes(serialization.Encoding.DER) for root in roots
    ]
    with pytest.raises(ValueError, match="no backend certificate authorities"):
        build_trust_store(other.public_bytes(serialization.Encoding.PEM))


def test_generator_rejects_invalid_certificate_input() -> None:
    with pytest.raises(ValueError):
        build_trust_store(b"-----BEGIN CERTIFICATE-----\ninvalid\n-----END CERTIFICATE-----\n")


def test_generator_excludes_compromised_anchors_even_if_source_contains_them() -> None:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)
    trusted = x509.load_pem_x509_certificates(STORE.read_bytes())[0]
    blocked = []
    for common_name in BLOCKED_ROOT_COMMON_NAMES:
        name = x509.Name([
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Google Trust Services LLC"),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        ])
        blocked.append(x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=30))
            .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
            .sign(key, hashes.SHA256()))
    source = b"".join(root.public_bytes(serialization.Encoding.PEM) for root in [trusted, *blocked])
    actual = x509.load_pem_x509_certificates(build_trust_store(source))
    assert [root.fingerprint(hashes.SHA256()) for root in actual] == [trusted.fingerprint(hashes.SHA256())]


def test_runtime_certifi_bundle_distrusts_compromised_emudhra_anchors() -> None:
    roots = x509.load_pem_x509_certificates(Path(certifi.where()).read_bytes())
    common_names = {item.value for root in roots for item in root.subject.get_attributes_for_oid(NameOID.COMMON_NAME)}
    assert not (common_names & BLOCKED_ROOT_COMMON_NAMES)
