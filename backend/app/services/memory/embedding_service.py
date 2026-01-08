"""Embedding service using Gemini text-embedding-004.

Provides batch embedding generation with chunking for large datasets.
Uses the same credential pattern as GeminiClient.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google import genai

logger = logging.getLogger(__name__)

# Gemini embedding model
EMBEDDING_MODEL = "text-embedding-004"
# Max texts per API call (Gemini limit)
MAX_BATCH_SIZE = 100
# Embedding dimension for text-embedding-004
EMBEDDING_DIMENSION = 768


class EmbeddingService:
    """Service for generating text embeddings using Gemini.

    Uses text-embedding-004 model which produces 768-dimensional embeddings.
    Supports batch embedding for efficiency (up to 100 texts per API call).

    Usage:
        service = EmbeddingService()
        embeddings = service.embed_batch(["text1", "text2", "text3"])
        # Returns list of 768-dim vectors
    """

    def __init__(self) -> None:
        """Initialize embedding service."""
        self._client: genai.Client | None = None
        self._has_credentials = self._check_credentials()
        logger.info(f"EmbeddingService initialized (available={self._has_credentials})")

    def _check_credentials(self) -> bool:
        """Check if Gemini credentials are available.

        Uses the same credential pattern as GeminiClient:
        1. GOOGLE_API_KEY or GEMINI_API_KEY environment variable
        2. ~/.gemini/.env file with GEMINI_API_KEY
        3. Application default credentials (gcloud auth)
        """
        # Check for API keys (multiple possible names)
        if os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY"):
            return True

        # Check ~/.gemini/.env for GEMINI_API_KEY
        gemini_env = Path.home() / ".gemini" / ".env"
        if gemini_env.exists():
            with open(gemini_env) as f:
                for line in f:
                    if line.startswith("GEMINI_API_KEY="):
                        key = line.strip().split("=", 1)[1]
                        os.environ["GOOGLE_API_KEY"] = key
                        return True

        # Check for application default credentials
        try:
            import google.auth

            google.auth.default()
            return True
        except Exception:
            return False

    def _get_client(self) -> genai.Client:
        """Get or create the Gemini client."""
        if self._client is None:
            from google import genai

            self._client = genai.Client()
        return self._client

    def is_available(self) -> bool:
        """Check if embedding service is available."""
        return self._has_credentials

    def embed_text(self, text: str) -> list[float]:
        """Embed a single text.

        Delegates to embed_batch for consistency.

        Args:
            text: Text to embed

        Returns:
            768-dimensional embedding vector
        """
        embeddings = self.embed_batch([text])
        return embeddings[0]

    def embed_pattern(self, title: str, content: str) -> list[float]:
        """Embed a pattern by combining title and content.

        Creates a single embedding from the concatenated title + content,
        suitable for semantic similarity search and deduplication.

        Args:
            title: Pattern title
            content: Pattern content/description

        Returns:
            768-dimensional embedding vector
        """
        combined = f"{title}\n\n{content}"
        return self.embed_text(combined)

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in batches.

        Chunks large batches into MAX_BATCH_SIZE (100) per API call.

        Args:
            texts: List of texts to embed

        Returns:
            List of 768-dimensional embedding vectors (same order as input)

        Raises:
            RuntimeError: If credentials are not available or API call fails
        """
        if not self._has_credentials:
            raise RuntimeError("Gemini credentials not available for embedding")

        if not texts:
            return []

        client = self._get_client()
        all_embeddings: list[list[float]] = []

        # Process in chunks of MAX_BATCH_SIZE
        for i in range(0, len(texts), MAX_BATCH_SIZE):
            chunk = texts[i : i + MAX_BATCH_SIZE]
            try:
                result = client.models.embed_content(
                    model=EMBEDDING_MODEL,
                    contents=chunk,  # type: ignore[arg-type]  # API accepts list[str]
                )

                # Extract embeddings from response
                if result.embeddings is None:
                    raise RuntimeError("No embeddings returned from API")
                for embedding in result.embeddings:
                    if embedding.values is None:
                        raise RuntimeError("Embedding values are None")
                    all_embeddings.append(list(embedding.values))

                logger.debug(f"Embedded {len(chunk)} texts in batch {i // MAX_BATCH_SIZE + 1}")

            except Exception as e:
                logger.error(f"Embedding batch failed: {e}")
                raise RuntimeError(f"Embedding batch failed: {e}") from e

        logger.info(f"Generated {len(all_embeddings)} embeddings in batches")
        return all_embeddings
