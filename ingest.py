import os
import uuid
import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from pypdf import PdfReader

from config import KNOWLEDGE_DIR, CHROMA_PATH, COLLECTION_NAME, EMBED_MODEL

def extract_text_from_file(filepath: str) -> str:
    ext = os.path.splitext(filepath)[1].lower()
    text = ""
    try:
        if ext == ".pdf":
            reader = PdfReader(filepath)
            text = "".join(t for page in reader.pages if (t := page.extract_text()))
        elif ext in (".txt", ".md"):
            with open(filepath, "r", encoding="utf-8") as f:
                text = f.read()
    except Exception as e:
        print(f"  ⚠️ Error reading {os.path.basename(filepath)}: {e}")
    return text.strip()

def chunk_text(text: str, chunk_size: int = 800, overlap: int = 100) -> list[str]:
    """Word-level sliding window chunker."""
    words = text.split()
    return [" ".join(words[i:i + chunk_size]) for i in range(0, len(words), chunk_size - overlap)]

def run_ingestion():
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("❌ Error: OPENAI_API_KEY is not set. Add it to your .env file.")
        return

    os.makedirs(KNOWLEDGE_DIR, exist_ok=True)
    files = [
        os.path.join(KNOWLEDGE_DIR, name)
        for name in sorted(os.listdir(KNOWLEDGE_DIR))
        if not name.startswith(".") and os.path.isfile(os.path.join(KNOWLEDGE_DIR, name))
    ]
    if not files:
        print("⚠️ No documents found. Place your resume, project docs, or notes in the knowledge/ folder.")
        return

    client = chromadb.PersistentClient(path=CHROMA_PATH)
    print("🗑️ Clearing old embeddings...")
    try:
        client.delete_collection(COLLECTION_NAME)
    except Exception:
        pass  # collection did not exist yet
    collection = client.create_collection(
        name=COLLECTION_NAME,
        embedding_function=OpenAIEmbeddingFunction(api_key=api_key, model_name=EMBED_MODEL),
    )

    print(f"📚 Ingesting {len(files)} document(s) into ChromaDB...")
    total_chunks = 0
    for filepath in files:
        filename = os.path.basename(filepath)
        print(f"  -> Processing {filename}...")
        chunks = chunk_text(extract_text_from_file(filepath))
        if not chunks:
            print("     ⚠️ Skipped (empty or unreadable).")
            continue
        collection.add(
            documents=chunks,
            metadatas=[{"source": filename}] * len(chunks),
            ids=[f"{filename}-{uuid.uuid4().hex[:8]}" for _ in chunks],
        )
        print(f"     ✅ Embedded {len(chunks)} chunks.")
        total_chunks += len(chunks)

    print(f"\n🎉 Ingestion complete! {total_chunks} chunks stored in {CHROMA_PATH}.")

if __name__ == "__main__":
    run_ingestion()
