import json
import secrets
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import datetime

SECRETS = Path("secrets")
SECRETS.mkdir(exist_ok=True)

users = {
    "admin": secrets.token_urlsafe(24),
    "alice": secrets.token_urlsafe(24),
    "bob": secrets.token_urlsafe(24),
}
(SECRETS / "users.json").write_text(json.dumps(users, indent=2), encoding="utf-8")

key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
subject = issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
cert = (
    x509.CertificateBuilder()
    .subject_name(subject).issuer_name(issuer)
    .public_key(key.public_key())
    .serial_number(x509.random_serial_number())
    .not_valid_before(datetime.datetime.utcnow())
    .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
    .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
    .sign(key, hashes.SHA256())
)

(SECRETS / "server.key").write_bytes(
    key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.TraditionalOpenSSL,
        encryption_algorithm=serialization.NoEncryption(),
    )
)
(SECRETS / "server.crt").write_bytes(cert.public_bytes(serialization.Encoding.PEM))

print("Generated secrets:")
for p in SECRETS.iterdir():
    print(f"  {p}")
print("\nPasswords:")
for login, pwd in users.items():
    print(f"  {login}: {pwd}")