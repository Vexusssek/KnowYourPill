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
        self.all_embeddings = None
        self.MAX_CONTEXT_CHARS = 3000

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
        self.all_embeddings = np.array(embeddings).astype('float32')
        dimension = self.all_embeddings.shape[1]

        self.index = faiss.IndexFlatL2(dimension)
        self.index.add(self.all_embeddings)

    def search(self, query: str, k: int = 5, lambda_param: float = 0.5) -> str:
        self._ensure_indexed()
        if not self.index or not self.chunks:
            return ""

        query_vector = self.model.encode([query])
        query_vector = np.array(query_vector).astype('float32')
        
        fetch_k = min(2 * k, len(self.chunks))
        distances, indices = self.index.search(query_vector, fetch_k)
        
        selected_indices = self._mmr(query_vector, indices[0], k, lambda_param)

        results = []
        current_length = 0
        for idx in selected_indices:
            if idx < len(self.chunks):
                chunk_text = f"[Źródło ID:{idx}] {self.chunks[idx]}"
                if current_length + len(chunk_text) + 1 > self.MAX_CONTEXT_CHARS:
                    results.append("... [Kontekst RAG przycięty ze względu na limit długości]")
                    break
                results.append(chunk_text)
                current_length += len(chunk_text) + 1

        return "\n".join(results)

    def _mmr(self, query_vector, indices, k, lambda_param):
        if not indices.size or k <= 0:
            return []
        
        valid_indices = [idx for idx in indices if idx != -1]
        if not valid_indices:
            return []

        candidate_embeddings = self.all_embeddings[valid_indices]
        
        query_norm = query_vector / np.linalg.norm(query_vector)
        candidate_norms = candidate_embeddings / np.linalg.norm(candidate_embeddings, axis=1, keepdims=True)
        
        similarities_to_query = np.dot(candidate_norms, query_norm.T).flatten()
        
        selected_indices = []
        selected_embeddings = []
        
        remaining_indices = list(range(len(valid_indices)))
        
        while len(selected_indices) < k and remaining_indices:
            mmr_scores = []
            for i in remaining_indices:
                sim_to_query = similarities_to_query[i]
                
                if not selected_embeddings:
                    sim_to_selected = 0
                else:
                    sim_to_selected = np.max(np.dot(selected_embeddings, candidate_norms[i]))
                
                score = lambda_param * sim_to_query - (1 - lambda_param) * sim_to_selected
                mmr_scores.append(score)
            
            best_idx_in_remaining = np.argmax(mmr_scores)
            best_idx_global = remaining_indices.pop(best_idx_in_remaining)
            
            selected_indices.append(valid_indices[best_idx_global])
            selected_embeddings.append(candidate_norms[best_idx_global])
            
        return selected_indices


rag_system = MedicalRAG()
