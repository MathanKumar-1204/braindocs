import logging
from typing import List, Dict, Any, Optional
from config import Config

logger = logging.getLogger(__name__)

_pinecone_index = None

def get_pinecone_index():
    global _pinecone_index
    if _pinecone_index is None:
        if Config.PINECONE_API_KEY and "your-pinecone" not in Config.PINECONE_API_KEY:
            try:
                from pinecone import Pinecone, ServerlessSpec
                pc = Pinecone(api_key=Config.PINECONE_API_KEY)
                index_name = Config.PINECONE_INDEX_NAME

                try:
                    _pinecone_index = pc.Index(index_name)
                    logger.info(f"Connected to Pinecone index: {index_name}")
                except Exception as e:
                    logger.info(f"Index check/create fallback for {index_name}: {e}")
                    existing_indexes = [idx.name for idx in pc.list_indexes()]
                    if index_name not in existing_indexes:
                        pc.create_index(
                            name=index_name,
                            dimension=384,
                            metric="cosine",
                            spec=ServerlessSpec(cloud="aws", region="us-east-1")
                        )
                    _pinecone_index = pc.Index(index_name)
            except Exception as e:
                logger.error(f"Error connecting to Pinecone: {e}")
                _pinecone_index = None
    return _pinecone_index


def upsert_vectors_to_namespace(username: str, doc_id: str, filename: str, chunks: List[str], embeddings: List[List[float]], target_namespace: Optional[str] = None, visibility: str = "public") -> bool:
    """
    Upserts document chunk vector embeddings into Pinecone under the target namespace
    (e.g., `{username}` for public, or `{username}-private` for private).
    """
    index = get_pinecone_index()
    namespace = (target_namespace or username).strip().lower()

    if not chunks or not embeddings or len(chunks) != len(embeddings):
        logger.warning("Empty or mismatched chunks/embeddings for vector upsert.")
        return False

    vectors = []
    for i, (chunk, emb) in enumerate(zip(chunks, embeddings)):
        vector_id = f"{doc_id}_chunk_{i}"
        metadata = {
            "document_id": str(doc_id),
            "filename": str(filename),
            "chunk_index": i,
            "text": str(chunk),
            "visibility": str(visibility),
            "namespace": str(namespace)
        }
        vectors.append({
            "id": vector_id,
            "values": emb,
            "metadata": metadata
        })

    if not index:
        logger.warning(f"Pinecone not configured. Simulating vector upsert of {len(vectors)} items into namespace '{namespace}'.")
        return True

    try:
        # Upsert vectors in batches of 100
        batch_size = 100
        for i in range(0, len(vectors), batch_size):
            batch = vectors[i:i + batch_size]
            index.upsert(vectors=batch, namespace=namespace)
        logger.info(f"Successfully upserted {len(vectors)} vectors into namespace '{namespace}'")
        return True
    except Exception as e:
        logger.error(f"Error upserting vectors to Pinecone namespace '{namespace}': {e}")
        return False


def query_vector_namespace(username: str, query_vector: List[float], top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Queries Pinecone index within the user's namespace (`{username}`).
    Returns list of matching text contexts with similarity scores.
    """
    index = get_pinecone_index()
    namespace = username.strip().lower()

    if not index:
        logger.warning(f"Pinecone index not configured. Returning fallback empty context for namespace '{namespace}'.")
        return []

    try:
        response = index.query(
            vector=query_vector,
            top_k=top_k,
            namespace=namespace,
            include_metadata=True
        )

        matches = []
        if response and hasattr(response, "matches"):
            for match in response.matches:
                metadata = match.metadata or {}
                matches.append({
                    "score": match.score,
                    "text": metadata.get("text", ""),
                    "filename": metadata.get("filename", ""),
                    "document_id": metadata.get("document_id", "")
                })
        return matches
    except Exception as e:
        logger.error(f"Error querying Pinecone namespace '{namespace}': {e}")
        return []


def delete_vectors_by_document(username: str, doc_id: str, chunk_count: int = 500, target_namespace: Optional[str] = None) -> bool:
    """
    Deletes all vector chunks associated with a specific document_id from the user's Pinecone namespace.
    """
    index = get_pinecone_index()
    namespace = (target_namespace or username).strip().lower()

    if not index:
        logger.warning(f"Pinecone not configured. Simulating vector deletion for doc_id {doc_id} in namespace '{namespace}'.")
        return True

    try:
        # Try metadata filter deletion first
        try:
            index.delete(filter={"document_id": str(doc_id)}, namespace=namespace)
            logger.info(f"Deleted vectors using metadata filter document_id={doc_id} in namespace '{namespace}'")
            return True
        except Exception:
            # Fallback ID-based deletion if filter deletion is not enabled
            vector_ids = [f"{doc_id}_chunk_{i}" for i in range(chunk_count)]
            index.delete(ids=vector_ids, namespace=namespace)
            logger.info(f"Deleted vector IDs for doc_id {doc_id} in namespace '{namespace}'")
            return True
    except Exception as e:
        logger.error(f"Error deleting document vectors from Pinecone namespace '{namespace}': {e}")
        return False
