"""Database upgrade v0.0.29 — encrypt existing plaintext LLM API keys"""
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import select, text

from app.db.base import SessionLocal, engine
from app.models.daily_summary import LLMProviderConfig
from app.core.security import encrypt_api_key, decrypt_api_key

logger = logging.getLogger(__name__)
DESCRIPTION = "Encrypt existing plaintext LLM API keys in llm_provider_configs table"


async def upgrade():
    print("\n" + "=" * 60)
    print("  Starting upgrade to v0.0.29")
    print("=" * 60 + "\n")

    async with SessionLocal() as db:
        result = await db.execute(select(LLMProviderConfig))
        configs = result.scalars().all()

        encrypted_count = 0
        skipped_count = 0

        for config in configs:
            if not config.api_key:
                skipped_count += 1
                continue

            # Check if already encrypted (Fernet ciphertext starts with 'gAAAAA')
            if config.api_key.startswith("gAAAAA"):
                skipped_count += 1
                continue

            # Encrypt the plaintext key
            try:
                encrypted = encrypt_api_key(config.api_key)
                # Verify decryption works
                decrypted = decrypt_api_key(encrypted)
                if decrypted != config.api_key:
                    print(f"  [WARN] Decryption verification failed for provider={config.provider}, skipping")
                    skipped_count += 1
                    continue

                config.api_key = encrypted
                encrypted_count += 1
                print(f"  [DONE] Encrypted API key for provider={config.provider}")
            except Exception as e:
                print(f"  [ERROR] Failed to encrypt key for provider={config.provider}: {e}")
                skipped_count += 1

        await db.commit()

    print(f"\n  Encrypted: {encrypted_count}, Skipped: {skipped_count}")

    print("\n" + "=" * 60)
    print("  Upgrade v0.0.29 complete!")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(upgrade())
