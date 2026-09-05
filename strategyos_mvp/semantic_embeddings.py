"""Pinned local multilingual embeddings; runtime never downloads or falls back."""
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path

MODEL_NAME='strategyos/multilingual-e5-small'
MODEL_REPOSITORY='Xenova/multilingual-e5-small'
MODEL_REVISION='761b726dd34fb83930e26aab4e9ac3899aa1fa78'
MODEL_FILE='onnx/model_quantized.onnx'
DIMENSIONS=384
COLLECTION='strategyos_multilingual_e5_761b726d_384_v1'


def configured():
    return bool(os.getenv('STRATEGYOS_EMBEDDING_MODEL_PATH','').strip())


@lru_cache(maxsize=1)
def model():
    root=Path(os.environ['STRATEGYOS_EMBEDDING_MODEL_PATH']).resolve()
    manifest=json.loads((root/'model-manifest.json').read_text())
    if manifest.get('revision')!=MODEL_REVISION or manifest.get('model_name')!=MODEL_NAME:
        raise RuntimeError('Embedding model identity does not match this release.')
    expected={MODEL_FILE,'tokenizer.json','config.json','tokenizer_config.json','special_tokens_map.json'}
    entries=manifest.get('files',{})
    if not expected.issubset(entries):
        raise RuntimeError('Embedding model manifest is incomplete.')
    for name,digest in entries.items():
        path=(root/name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
            raise RuntimeError('Embedding model file is missing or changed.')
    from fastembed import TextEmbedding
    from fastembed.common.model_description import PoolingType, ModelSource
    TextEmbedding.add_custom_model(model=MODEL_NAME, pooling=PoolingType.MEAN, normalization=True,
        sources=ModelSource(hf=MODEL_REPOSITORY), dim=DIMENSIONS, model_file=MODEL_FILE,
        license="MIT", description="Pinned multilingual E5 small quantized retrieval model")
    threads = int(os.getenv('STRATEGYOS_EMBEDDING_THREADS', '1'))
    if not 1 <= threads <= 4:
        raise ValueError('Embedding CPU threads must be between one and four.')
    return TextEmbedding(model_name=MODEL_NAME,specific_model_path=str(root),local_files_only=True,
                         threads=threads,providers=['CPUExecutionProvider'])


@lru_cache(maxsize=2048)
def _cached(text):
    vector=next(iter(model().embed([text]))).tolist()
    if len(vector)!=DIMENSIONS:
        raise RuntimeError('Unexpected embedding dimensions.')
    norm = math.sqrt(sum(float(value) ** 2 for value in vector))
    if not math.isfinite(norm) or norm <= 0:
        raise RuntimeError("Embedding model returned a non-finite or empty vector.")
    return tuple(float(value) / norm for value in vector)


def embed(text, *, query=False):
    return list(_cached(("query: " if query else "passage: ") + str(text)))


def embed_many(texts):
    if not texts:
        return []
    result = []
    for vector in model().embed(["passage: " + str(text) for text in texts], batch_size=16):
        values = vector.tolist()
        norm = math.sqrt(sum(float(value) ** 2 for value in values))
        if len(values) != DIMENSIONS or not math.isfinite(norm) or norm <= 0:
            raise RuntimeError("Embedding model returned an invalid vector.")
        result.append([float(value) / norm for value in values])
    if len(result) != len(texts):
        raise RuntimeError("Embedding model returned an incomplete batch.")
    return result
