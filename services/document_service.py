import io
import csv
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

# Lazy initialization of sentence-transformer model to avoid long startup times
_model = None

def get_embedding_model():
    global _model
    if _model is None:
        try:
            from sentence_transformers import SentenceTransformer
            from config import Config
            logger.info(f"Loading embedding model: {Config.EMBEDDING_MODEL_NAME}")
            _model = SentenceTransformer(Config.EMBEDDING_MODEL_NAME)
        except Exception as e:
            logger.error(f"Error loading SentenceTransformer: {e}")
            _model = None
    return _model


def extract_text(file_bytes: bytes, filename: str) -> str:
    """
    Extract text content from uploaded file bytes based on file extension.
    Supports PDF, DOCX, TXT, and CSV formats.
    """
    ext = filename.split(".")[-1].lower()
    text = ""

    try:
        if ext == "pdf":
            import pypdf
            reader = pypdf.PdfReader(io.BytesIO(file_bytes))
            text_parts = []
            for page in reader.pages:
                extracted = page.extract_text()
                if extracted:
                    text_parts.append(extracted)
            text = "\n\n".join(text_parts)

        elif ext == "docx":
            import docx
            doc = docx.Document(io.BytesIO(file_bytes))
            text_parts = [para.text for para in doc.paragraphs if para.text.strip()]
            text = "\n\n".join(text_parts)

        elif ext in ["csv", "txt"]:
            text = file_bytes.decode("utf-8", errors="ignore")
            
        else:
            raise ValueError(f"Unsupported file format: {ext}")

    except Exception as e:
        logger.error(f"Error extracting text from {filename}: {e}")
        raise e

    return text.strip()


def chunk_text(text: str, chunk_size: int = 150, overlap: int = 25) -> List[str]:
    """
    Splits long text content into concise overlapping text chunks (~800 characters) for Pinecone vector indexing.
    """
    if not text:
        return []

    words = text.split()
    chunks = []
    
    if len(words) <= chunk_size:
        return [" ".join(words)]

    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)
        start += (chunk_size - overlap)
        if start >= len(words):
            break

    return chunks


import requests

def _hf_inference_embeddings(text_chunks: List[str]) -> Optional[List[List[float]]]:
    """Uses Hugging Face free Inference API for zero-RAM 384-dim embedding generation."""
    try:
        url = "https://api-inference.huggingface.co/pipeline/feature-extraction/sentence-transformers/all-MiniLM-L6-v2"
        response = requests.post(url, json={"inputs": text_chunks, "options": {"wait_for_model": True}}, timeout=10)
        if response.status_code == 200:
            res = response.json()
            if isinstance(res, list) and len(res) > 0:
                embeddings = []
                for item in res:
                    if isinstance(item, list) and len(item) > 0 and isinstance(item[0], list):
                        # Mean pool token vectors
                        vec = [sum(col) / len(col) for col in zip(*item)]
                        embeddings.append(vec)
                    elif isinstance(item, list) and len(item) > 0 and isinstance(item[0], (int, float)):
                        embeddings.append(item)
                if len(embeddings) == len(text_chunks):
                    return embeddings
    except Exception as e:
        logger.warning(f"Hugging Face Inference API exception: {e}")
    return None


def generate_embeddings(text_chunks: List[str]) -> List[List[float]]:
    """
    Generates 384-dimensional vector embeddings for a list of text chunks.
    Tries lightweight Hugging Face API first, falling back to local SentenceTransformer.
    """
    # 1. Try free cloud API first (< 40MB RAM required)
    api_res = _hf_inference_embeddings(text_chunks)
    if api_res:
        return api_res

    # 2. Local model fallback
    model = get_embedding_model()
    if model:
        embeddings = model.encode(text_chunks, show_progress_bar=False)
        return [emb.tolist() for emb in embeddings]
    else:
        logger.warning("Using fallback zero vectors for embeddings.")
        return [[0.0] * 384 for _ in text_chunks]


def generate_single_embedding(text: str) -> List[float]:
    """
    Generates embedding vector for a single query string.
    """
    res = generate_embeddings([text])
    return res[0] if res else [0.0] * 384
