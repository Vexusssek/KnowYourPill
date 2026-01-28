from sentence_transformers import SentenceTransformer
import faiss
import numpy as np
import os


class MedicalRAG:
    def __init__(self, knowledge_file="knowledge.txt"):
        self.embedding_model = 'all-MiniLM-L6-v2'
        self._model = None
        self.knowledge_file = knowledge_file
        self.chunks = []
        self.index = None

    @property
    def model(self):
        if self._model is None:
            self._model = SentenceTransformer(self.embedding_model)
        return self._model

    def _ensure_indexed(self):
        if self.index is None:
            self._build_index()

    def _build_index(self):
        if not os.path.exists(self.knowledge_file):
            return

        with open(self.knowledge_file, "r", encoding="utf-8") as f:
            lines = f.readlines()

        self.chunks = [line.strip() for line in lines if line.strip()]

        if not self.chunks:
            return

        embeddings = self.model.encode(self.chunks, show_progress_bar=False)
        dimension = embeddings.shape[1]

        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(np.array(embeddings).astype('float32'))

    def search(self, query: str, k: int = 2) -> str:
        self._ensure_indexed()
        if not self.index or not self.chunks:
            return ""

        query_vector = self.model.encode([query])
        distances, indices = self.index.search(np.array(query_vector).astype('float32'), k)

        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.chunks):
                results.append(f"[Źródło ID:{idx}] {self.chunks[idx]}")

        return "\n".join(results)


rag_system = MedicalRAG()
