"""
crypto_audit.py — Asymmetric Audit Signing with Hardware Secure Element Support
Replaces symmetric HMAC-SHA256 with Ed25519 asymmetric signatures.
Supports software Ed25519 and hardware secure elements (ATECC608A, TPM 2.0).
"""

import os
import json
import base64
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional
from pathlib import Path

# Ed25519 implementation
try:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey, Ed25519PublicKey
    )
    from cryptography.hazmat.primitives import serialization
    CRYPTO_AVAILABLE = True
except ImportError:
    CRYPTO_AVAILABLE = False
    Ed25519PrivateKey = None
    Ed25519PublicKey = None

# Hardware secure element support
HARDWARE_AVAILABLE = False
try:
    from atecc import ATECC
    HARDWARE_AVAILABLE = True
except ImportError:
    pass
try:
    from tpm2_pytss import ESAPI
    HARDWARE_AVAILABLE = True
except ImportError:
    pass


@dataclass
class AuditKeyPair:
    """Asymmetric key pair for audit signing."""
    private_key: 'Ed25519PrivateKey'
    public_key: 'Ed25519PublicKey'
    key_id: str
    source: str  # "software", "atecc608a", "tpm"


class AuditSigner(ABC):
    """Abstract interface for audit signing backends."""
    
    @abstractmethod
    def sign(self, message: bytes) -> bytes:
        """Sign a message, return signature bytes."""
        pass
    
    @abstractmethod
    def verify(self, message: bytes, signature: bytes) -> bool:
        """Verify a signature against a message."""
        pass
    
    @abstractmethod
    def get_public_key_bytes(self) -> bytes:
        """Return public key as raw bytes."""
        pass
    
    @abstractmethod
    def get_key_id(self) -> str:
        """Return key identifier."""
        pass


class SoftwareEd25519Signer(AuditSigner):
    """Software Ed25519 signer using cryptography library."""
    
    def __init__(self, private_key: 'Ed25519PrivateKey' = None, key_id: str = "audit-key-1"):
        if not CRYPTO_AVAILABLE:
            raise RuntimeError("cryptography library required. pip install cryptography")
        
        if private_key is None:
            private_key = Ed25519PrivateKey.generate()
        
        self._private_key = private_key
        self._public_key = private_key.public_key()
        self._key_id = key_id
    
    def sign(self, message: bytes) -> bytes:
        return self._private_key.sign(message)
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        try:
            self._public_key.verify(signature, message)
            return True
        except Exception:
            return False
    
    def get_public_key_bytes(self) -> bytes:
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw
        )
    
    def get_key_id(self) -> str:
        return self._key_id
    
    def export_private_key_pem(self, password: bytes = None) -> bytes:
        """Export private key as PEM (for backup)."""
        return self._private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.BestAvailableEncryption(password) if password else serialization.NoEncryption()
        )
    
    def export_public_key_pem(self) -> bytes:
        """Export public key as PEM."""
        return self._public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        )
    
    @classmethod
    def from_private_key_pem(cls, pem: bytes, password: bytes = None, key_id: str = "audit-key-1") -> 'SoftwareEd25519Signer':
        """Load signer from PEM-encoded private key."""
        private_key = serialization.load_pem_private_key(pem, password=password)
        if not isinstance(private_key, Ed25519PrivateKey):
            raise ValueError("Key is not Ed25519")
        return cls(private_key=private_key, key_id=key_id)
    
    @classmethod
    def from_public_key_pem(cls, pem: bytes, key_id: str = "audit-key-1") -> 'SoftwareEd25519Signer':
        """Create verifier from PEM-encoded public key."""
        public_key = serialization.load_pem_public_key(pem)
        if not isinstance(public_key, Ed25519PublicKey):
            raise ValueError("Key is not Ed25519")
        signer = cls.__new__(cls)
        signer._public_key = public_key
        signer._private_key = None  # Verification only
        signer._key_id = key_id
        return signer


class ATECC608ASigner(AuditSigner):
    """
    ATECC608A Hardware Secure Element signer.
    Requires atecc driver (pip install atecc) or custom I2C driver.
    """
    
    def __init__(self, i2c_bus: int = 1, address: int = 0x60, slot: int = 0, key_id: str = "atecc608a-key"):
        self._i2c_bus = i2c_bus
        self._address = address
        self._slot = slot
        self._key_id = key_id
        self._public_key_bytes = None
        self._initialize()
    
    def _initialize(self):
        """Initialize ATECC608A and extract public key."""
        try:
            # Try to import atecc driver
            from atecc import ATECC
            self._device = ATECC(self._i2c_bus, self._address)
            # Generate or load key in slot
            self._device.generate_key(self._slot)
            self._public_key_bytes = self._device.get_public_key(self._slot)
        except ImportError:
            raise RuntimeError("atecc driver not installed. pip install atecc")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize ATECC608A: {e}")
    
    def sign(self, message: bytes) -> bytes:
        """Sign using ATECC608A hardware."""
        # ATECC608A signs SHA256 digest
        import hashlib
        digest = hashlib.sha256(message).digest()
        return self._device.sign(self._slot, digest)
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        """Verify using public key (software fallback)."""
        if self._public_key_bytes is None:
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
            from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
            from cryptography.hazmat.primitives import hashes
            
            # ATECC608A uses ECDSA P-256
            from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1
            from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
            
            public_key = EllipticCurvePublicKey.from_encoded_point(SECP256R1(), self._public_key_bytes)
            public_key.verify(signature, message, hashes.SHA256())
            return True
        except Exception:
            return False
    
    def get_public_key_bytes(self) -> bytes:
        if self._public_key_bytes is None:
            # Derive from device
            self._public_key_bytes = self._device.get_public_key(self._slot)
        return self._public_key_bytes
    
    def get_key_id(self) -> str:
        return self._key_id


class TPMSigner(AuditSigner):
    """
    TPM 2.0 Hardware signer.
    Requires tpm2-pytss (pip install tpm2-pytss) or similar TPM stack.
    """
    
    def __init__(self, tcti: str = "device:/dev/tpmrm0", key_handle: int = 0x81000001, key_id: str = "tpm-key"):
        self._tcti = tcti
        self._key_handle = key_handle
        self._key_id = key_id
        self._public_key_bytes = None
        self._esys_ctx = None
        self._initialize()
    
    def _initialize(self):
        """Initialize TPM context and load key."""
        try:
            from tpm2_pytss import ESAPI, TCTI, TPM2_ALG_ECDSA, TPM2_ALG_SHA256
            from tpm2_pytss.tsskey import TSSPrivKey
            
            self._esys_ctx = ESAPI(tcti=self._tcti)
            self._esys_ctx.startup()
            
            # Load or create key
            try:
                self._key = TSSPrivKey.from_handle(self._esys_ctx, self._key_handle)
            except:
                # Create new key if not exists
                self._key = self._esys_ctx.create_primary(
                    in_public={
                        'type': 'ecc',
                        'scheme': 'ecdsa',
                        'curve': 'nist_p256',  # or nist_p384
                    }
                )
                self._esys_ctx.evict_control(self._key_handle, self._key.handle)
            
            # Get public key
            self._public_key_bytes = self._key.public_key().public_bytes_raw()
            
        except ImportError:
            raise RuntimeError("tpm2-pytss not installed. pip install tpm2-pytss")
        except Exception as e:
            raise RuntimeError(f"Failed to initialize TPM: {e}")
    
    def sign(self, message: bytes) -> bytes:
        """Sign using TPM."""
        import hashlib
        digest = hashlib.sha256(message).digest()
        # TPM signs the digest
        return self._key.sign(digest)
    
    def verify(self, message: bytes, signature: bytes) -> bool:
        """Verify using public key."""
        if self._public_key_bytes is None:
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric.ec import EllipticCurvePublicKey
            from cryptography.hazmat.primitives.asymmetric.ec import SECP256R1
            from cryptography.hazmat.primitives import hashes
            
            # TPM uses ECDSA P-256
            public_key = EllipticCurvePublicKey.from_encoded_point(SECP256R1(), self._public_key_bytes)
            public_key.verify(signature, message, hashes.SHA256())
            return True
        except Exception as e:
            # Log the exception for debugging
            import logging
            logging.debug(f"TPM signature verification failed: {e}")
            return False
    
    def get_public_key_bytes(self) -> bytes:
        return self._public_key_bytes
    
    def get_key_id(self) -> str:
        return self._key_id


# Factory function for getting the right signer
def get_audit_signer() -> AuditSigner:
    """
    Factory to get the configured audit signer.
    Configured via environment variables:
    - AUDIT_SIGNER: software|atecc608a|tpm
    - AUDIT_KEY_PATH: path to private key PEM (for software)
    - AUDIT_KEY_ID: key identifier
    """
    import os
    
    signer_type = os.getenv("AUDIT_SIGNER", "software").lower()
    key_id = os.getenv("AUDIT_KEY_ID", "audit-key-1")
    
    if signer_type == "software":
        key_path = os.getenv("AUDIT_KEY_PATH")
        if key_path and os.path.exists(key_path):
            with open(key_path, "rb") as f:
                pem = f.read()
            password = os.getenv("AUDIT_KEY_PASSWORD", "").encode() or None
            return SoftwareEd25519Signer.from_private_key_pem(pem, password=password, key_id=key_id)
        else:
            # Generate or load from default location
            default_path = Path.home() / ".secureguard" / "audit_key.pem"
            if default_path.exists():
                with open(default_path, "rb") as f:
                    pem = f.read()
                return SoftwareEd25519Signer.from_private_key_pem(pem, key_id=key_id)
            else:
                # Generate new key
                signer = SoftwareEd25519Signer(key_id=key_id)
                # Save to default location
                default_path.parent.mkdir(parents=True, exist_ok=True)
                with open(default_path, "wb") as f:
                    f.write(signer.export_private_key_pem())
                return signer
    
    elif signer_type == "atecc608a":
        i2c_bus = int(os.getenv("ATECC_I2C_BUS", "1"))
        address = int(os.getenv("ATECC_ADDRESS", "0x60"), 16)
        slot = int(os.getenv("ATECC_SLOT", "0"))
        return ATECC608ASigner(i2c_bus=i2c_bus, address=address, slot=slot, key_id=key_id)
    
    elif signer_type == "tpm":
        tcti = os.getenv("TPM_TCTI", "device:/dev/tpmrm0")
        key_handle = int(os.getenv("TPM_KEY_HANDLE", "0x81000001"), 16)
        return TPMSigner(tcti=tcti, key_handle=key_handle, key_id=key_id)
    
    else:
        raise ValueError(f"Unknown audit signer type: {signer_type}")


# Global singleton
_audit_signer: Optional[AuditSigner] = None


def get_audit_signer_singleton() -> AuditSigner:
    """Get or create the global audit signer singleton."""
    global _audit_signer
    if _audit_signer is None:
        _audit_signer = get_audit_signer()
    return _audit_signer


def set_audit_signer(signer: AuditSigner) -> None:
    """Set a custom audit signer (for testing)."""
    global _audit_signer
    _audit_signer = signer


# Verification utility
def verify_chain_signature(record_canonical: str, previous_hash: str, signature_b64: str, public_key_b64: str) -> bool:
    """Verify a chain signature using Ed25519 public key."""
    if not CRYPTO_AVAILABLE:
        return False
    
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        
        public_key_bytes = base64.b64decode(public_key_b64)
        public_key = Ed25519PublicKey.from_public_bytes(public_key_bytes)
        
        message = (record_canonical + previous_hash).encode("utf-8")
        signature = base64.b64decode(signature_b64)
        
        public_key.verify(signature, message)
        return True
    except Exception:
        return False


# Genesis hash for chain (uses SHA256 of "GENESIS" as deterministic root)
def compute_genesis_hash() -> str:
    import hashlib
    return hashlib.sha256(b"GENESIS").hexdigest()
