"""Build the Mini backend trust store from reviewed Mozilla root certificates."""

from __future__ import annotations

import argparse
import hashlib
from importlib.metadata import version
import json
from pathlib import Path

import certifi
from cryptography import x509
from cryptography.hazmat.primitives import serialization
from cryptography.x509.oid import NameOID


TRUSTED_CA_ORGANIZATIONS = frozenset({
    "Google Trust Services LLC", "Internet Security Research Group",
    "SSL Corporation", "Sectigo Limited", "COMODO CA Limited", "The USERTRUST Network",
})
BLOCKED_ROOT_COMMON_NAMES = frozenset({
    "AAA Certificate Services",
    "emSign ECC Root CA - G3",
})


def build_trust_store(pem: bytes) -> bytes:
    """Select Mozilla roots for the backend edge certificate authorities."""
    certificates = x509.load_pem_x509_certificates(pem)
    selected = [certificate for certificate in certificates if (
        any(item.value in TRUSTED_CA_ORGANIZATIONS
            for item in certificate.subject.get_attributes_for_oid(NameOID.ORGANIZATION_NAME))
        and not any(item.value in BLOCKED_ROOT_COMMON_NAMES
                    for item in certificate.subject.get_attributes_for_oid(NameOID.COMMON_NAME))
    )]
    if not selected:
        raise ValueError("no backend certificate authorities in source trust store")
    selected.sort(key=lambda certificate: certificate.subject.public_bytes())
    return b"".join(certificate.public_bytes(serialization.Encoding.PEM) for certificate in selected)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("mini/certs/backend.pem"))
    args = parser.parse_args()
    pem = Path(certifi.where()).read_bytes()
    store = build_trust_store(pem)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(store)
    metadata = {
        "source": "https://github.com/certifi/python-certifi",
        "certifi_version": version("certifi"),
        "source_sha256": hashlib.sha256(pem).hexdigest(),
        "store_sha256": hashlib.sha256(store).hexdigest(),
        "certificates": len(x509.load_pem_x509_certificates(store)),
        "organizations": sorted(TRUSTED_CA_ORGANIZATIONS),
        "format": "PEM",
    }
    args.output.with_suffix(".json").write_text(json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {metadata['certificates']} roots in {len(store)} bytes")


if __name__ == "__main__":
    main()
