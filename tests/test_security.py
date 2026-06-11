"""
Tests for the security module (Fernet encryption).
"""

from app.core.security import encrypt_token, decrypt_token


class TestTokenEncryption:
    """Tests for Fernet-based token encryption/decryption."""

    def test_encrypt_decrypt_roundtrip(self):
        """Encrypted token should decrypt back to the original value."""
        original = "EAABsbCS1iZCgB...test_token_12345"
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)

        assert decrypted == original
        assert encrypted != original

    def test_encrypted_output_differs_from_input(self):
        """Encrypted output should not contain the plaintext."""
        original = "my_secret_meta_token"
        encrypted = encrypt_token(original)

        assert original not in encrypted

    def test_different_tokens_produce_different_ciphertexts(self):
        """Different plaintexts should produce different ciphertexts."""
        token_a = encrypt_token("token_alpha")
        token_b = encrypt_token("token_beta")

        assert token_a != token_b

    def test_empty_string_encryption(self):
        """Should handle empty string without error."""
        original = ""
        encrypted = encrypt_token(original)
        decrypted = decrypt_token(encrypted)

        assert decrypted == original
