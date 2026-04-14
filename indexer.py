import os
import faiss
import numpy as np
from sentence_transformers import SentenceTransformer
from config import CSV_SOURCES, FAISS_INDEX_DIR

# Embedding dimension for all-MiniLM-L6-v2
EMBEDDING_DIM = 384
MODEL_NAME_EMBEDDING = "all-MiniLM-L6-v2"


def build_index():
    """Build a FAISS index from all data source descriptions in CSV_SOURCES.

    Each source's description gets embedded using sentence-transformers.
    The embeddings are stored in a FAISS flat index, and a mapping file
    tracks which index position corresponds to which table name.
    """
    table_names = list(CSV_SOURCES.keys())
    descriptions = [source["description"] for source in CSV_SOURCES.values()]

    # Load embedding model
    model = SentenceTransformer(MODEL_NAME_EMBEDDING)

    # Embed all descriptions
    embeddings = model.encode(descriptions, convert_to_numpy=True).astype("float32")

    # Build FAISS index
    index = faiss.IndexFlatL2(EMBEDDING_DIM)
    index.add(embeddings)

    # Save index and metadata
    os.makedirs(FAISS_INDEX_DIR, exist_ok=True)
    faiss.write_index(index, os.path.join(FAISS_INDEX_DIR, "index.faiss"))

    # Save table name mapping for query-time use
    import pickle
    metadata = {
        "table_names": table_names,
        "descriptions": descriptions,
        "model_name": MODEL_NAME_EMBEDDING,
    }
    with open(os.path.join(FAISS_INDEX_DIR, "metadata.pkl"), "wb") as f:
        pickle.dump(metadata, f)

    print(f"Indexed {len(table_names)} source(s):")
    for name, desc in zip(table_names, descriptions):
        print(f"  - {name}: {desc[:80]}...")
    print(f"\nFAISS index saved to {FAISS_INDEX_DIR}")


def search_index(query: str, top_k: int = 1) -> list[dict]:
    """Search the FAISS index for the most relevant data source(s).

    Returns a list of dicts with 'table_name', 'description', and 'distance'.
    """
    import pickle

    # Load index and metadata
    index = faiss.read_index(os.path.join(FAISS_INDEX_DIR, "index.faiss"))
    with open(os.path.join(FAISS_INDEX_DIR, "metadata.pkl"), "rb") as f:
        metadata = pickle.load(f)

    model_name = metadata.get("model_name", MODEL_NAME_EMBEDDING)
    table_names = metadata["table_names"]
    descriptions = metadata["descriptions"]

    # Load embedding model and embed the query
    model = SentenceTransformer(model_name)
    query_embedding = model.encode([query], convert_to_numpy=True).astype("float32")

    # Search
    distances, indices = index.search(query_embedding, top_k)

    results = []
    for dist, idx in zip(distances[0], indices[0]):
        if idx < len(table_names):
            results.append({
                "table_name": table_names[idx],
                "description": descriptions[idx],
                "distance": float(dist),
            })
    return results


if __name__ == "__main__":
    build_index()

    # Quick test
    print("\n--- Test Search ---")
    test_queries = [
        "What were total sales last quarter?",
        "Who is the top performing sales rep?",
        "Which region has the most revenue?",
    ]
    for q in test_queries:
        results = search_index(q)
        print(f"Q: {q}")
        print(f"  -> {results[0]['table_name']} (distance: {results[0]['distance']:.4f})")
