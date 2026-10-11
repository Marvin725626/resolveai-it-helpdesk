"""BM25 + dense retrieval, RRF fusion, lexical reranking.

SQLite is a small-corpus offline fallback. PostgreSQL ranks vectors in pgvector
and uses its full-text search index; it does not transfer all vectors to Python.
"""
import hashlib
import math
import re
from collections import Counter

import httpx
from sqlalchemy import func, select

from app.core.config import settings
from app.helpdesk.models import RunbookChunk


def tokenize(text: str) -> list[str]:
    text = text.lower()
    words = re.findall(r"[a-z0-9_-]+", text)
    for phrase in re.findall(r"[\u4e00-\u9fff]+", text):
        words.extend(phrase[i:i + 2] for i in range(len(phrase) - 1))
    return words


def local_embedding(text: str) -> list[float]:
    vector = [0.0] * settings.IT_EMBEDDING_DIMENSION
    for word in tokenize(text):
        digest = hashlib.sha256(word.encode()).digest()
        vector[int.from_bytes(digest[:4], "little") % len(vector)] += 1
    norm = math.sqrt(sum(x * x for x in vector)) or 1
    return [x / norm for x in vector]


def embedding_identity() -> str:
    return f"openai:{settings.OPENAI_EMBEDDING_MODEL}" if settings.IT_EMBEDDING_PROVIDER == "openai" else "local-hash-v1"


async def embed(texts: list[str]) -> list[list[float]]:
    if settings.IT_EMBEDDING_PROVIDER == "local":
        return [local_embedding(t) for t in texts]
    if not settings.OPENAI_API_KEY:
        raise ValueError("OPENAI_API_KEY is required for OpenAI embeddings")
    async with httpx.AsyncClient(timeout=30) as client:
        response = await client.post(
            settings.OPENAI_BASE_URL.rstrip("/") + "/embeddings",
            headers={"Authorization": f"Bearer {settings.OPENAI_API_KEY}"},
            json={"model": settings.OPENAI_EMBEDDING_MODEL, "input": texts, "dimensions": settings.IT_EMBEDDING_DIMENSION},
        )
        response.raise_for_status()
        vectors = [x["embedding"] for x in sorted(response.json()["data"], key=lambda x: x["index"])]
    if len(vectors) != len(texts) or any(len(v) != settings.IT_EMBEDDING_DIMENSION for v in vectors):
        raise ValueError("Embedding dimension/count mismatch; reindex with matching settings")
    return vectors


async def index_runbook(db, tenant_id: str, item: dict) -> int:
    # Paragraph boundaries preserve whole troubleshooting steps and source codes.
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", item["content"]) if p.strip()]
    chunks = []
    for paragraph in paragraphs:
        if chunks and len(chunks[-1]) + len(paragraph) < 900:
            chunks[-1] += "\n\n" + paragraph
        else:
            chunks.append(paragraph)
    vectors = await embed([item["title"] + " " + item.get("keywords", "") + " " + p for p in chunks])
    for i, (content, vector) in enumerate(zip(chunks, vectors)):
        search = " ".join(tokenize(item["title"] + " " + item.get("keywords", "") + " " + content))
        db.add(RunbookChunk(tenant_id=tenant_id, code=item["code"], chunk_index=str(i), title=item["title"],
                           content=content, keywords=item.get("keywords", ""), search_text=search,
                           embedding=vector, embedding_provider=embedding_identity()))
    await db.flush()
    return len(chunks)


def bm25(query: list[str], documents: list[list[str]]) -> list[float]:
    if not documents:
        return []
    average = sum(map(len, documents)) / len(documents) or 1
    df = Counter(word for words in documents for word in set(words))
    scores = []
    for words in documents:
        counts = Counter(words)
        score = 0.0
        for word in set(query):
            freq = counts[word]
            idf = math.log(1 + (len(documents) - df[word] + 0.5) / (df[word] + 0.5))
            score += idf * freq * 2.5 / (freq + 1.5 * (0.25 + 0.75 * len(words) / average))
        scores.append(score)
    return scores


async def retrieve(db, tenant_id: str, query: str, top_k: int = 4) -> list[dict]:
    q_tokens = tokenize(query)
    q_vec = (await embed([query]))[0]
    base = select(RunbookChunk).where(RunbookChunk.tenant_id == tenant_id,
                                    RunbookChunk.embedding_provider == embedding_identity())
    if db.bind.dialect.name == "postgresql":
        dense = list((await db.scalars(base.order_by(RunbookChunk.embedding.cosine_distance(q_vec)).limit(12))).all())
        tsquery = func.to_tsquery("simple", " | ".join(q_tokens) or "__empty__")
        vector = func.to_tsvector("simple", RunbookChunk.search_text)
        sparse = list((await db.scalars(base.where(vector.op("@@")(tsquery)).order_by(func.ts_rank_cd(vector, tsquery).desc()).limit(12))).all())
    else:
        rows = list((await db.scalars(base)).all())
        sparse_scores = bm25(q_tokens, [r.search_text.split() for r in rows])
        sparse = [r for r, score in sorted(zip(rows, sparse_scores), key=lambda x: x[1], reverse=True) if score > 0][:12]
        dense = sorted(rows, key=lambda r: sum(a * b for a, b in zip(q_vec, r.embedding)), reverse=True)[:12]
    fusion: dict = {}
    objects: dict = {}
    for ranking in (dense, sparse):
        for rank, row in enumerate(ranking, 1):
            fusion[row.id] = fusion.get(row.id, 0) + 1 / (60 + rank)
            objects[row.id] = row
    results = []
    for identity, row in objects.items():
        overlap = len(set(q_tokens) & set(row.search_text.split())) / max(len(set(q_tokens)), 1)
        # Lexical reranking is transparent and deterministic, not a cross encoder.
        title_overlap = len(set(q_tokens) & set(tokenize(row.title))) / max(len(set(q_tokens)), 1)
        score = fusion[identity] * (1 + overlap + 2 * title_overlap)
        results.append({"chunk_id": row.id, "code": row.code, "title": row.title, "content": row.content,
                        "overlap": round(overlap, 4), "rrf_score": round(fusion[identity], 5), "score": round(score, 5)})
    return sorted(results, key=lambda x: x["score"], reverse=True)[:top_k]
