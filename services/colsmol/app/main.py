"""GPU-backed ColSmol multi-vector embedding API for the drawing MVP."""

from __future__ import annotations

import io
import os
import threading
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, Field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_int(name: str, default: int, minimum: int = 1) -> int:
    raw = (os.getenv(name) or str(default)).strip()
    try:
        return max(int(raw), minimum)
    except ValueError:
        return default


class QueryRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=4000)


class ColSmolRuntime:
    """Loads the model once and serializes GPU inference for an 8 GB laptop GPU."""

    def __init__(self) -> None:
        self.model_name = os.getenv("COLSMOL_MODEL", "vidore/colSmol-256M").strip()
        self.dtype_name = os.getenv("COLSMOL_DTYPE", "float16").strip().lower()
        self.require_cuda = _env_bool("COLSMOL_REQUIRE_CUDA", True)
        self.max_image_edge = _env_int("COLSMOL_MAX_IMAGE_EDGE", 1536, 256)
        self.max_upload_bytes = _env_int(
            "COLSMOL_MAX_UPLOAD_BYTES", 25 * 1024 * 1024, 1024
        )
        self.skip_model_load = _env_bool("COLSMOL_SKIP_MODEL_LOAD", False)

        self.model: Any = None
        self.processor: Any = None
        self.torch: Any = None
        self.device = "uninitialized"
        self.gpu_name: str | None = None
        self.total_vram_bytes: int | None = None
        self.embedding_dimension: int | None = None
        self.load_error: str | None = None
        self.ready = False
        self._lock = threading.Lock()

    def load(self) -> None:
        if self.skip_model_load:
            self.device = "test"
            return

        import torch
        from colpali_engine.models import ColIdefics3, ColIdefics3Processor

        self.torch = torch
        cuda_available = torch.cuda.is_available()
        if self.require_cuda and not cuda_available:
            raise RuntimeError(
                "CUDA is required but unavailable. Confirm Docker Desktop GPU support."
            )

        if cuda_available:
            self.device = "cuda:0"
            self.gpu_name = torch.cuda.get_device_name(0)
            self.total_vram_bytes = int(torch.cuda.get_device_properties(0).total_memory)
            if self.dtype_name == "bfloat16" and torch.cuda.is_bf16_supported():
                dtype = torch.bfloat16
                self.dtype_name = "bfloat16"
            else:
                dtype = torch.float16
                self.dtype_name = "float16"
        else:
            self.device = "cpu"
            dtype = torch.float32
            self.dtype_name = "float32"

        self.model = ColIdefics3.from_pretrained(
            self.model_name,
            torch_dtype=dtype,
            attn_implementation="eager",
            low_cpu_mem_usage=True,
        ).eval()
        self.model.to(self.device)
        self.processor = ColIdefics3Processor.from_pretrained(self.model_name)

        with self._lock, self.torch.inference_mode():
            batch = self.processor.process_queries(["architectural drawing"]).to(
                self.device
            )
            probe = self._serialize(self.model(**batch))
        self.embedding_dimension = int(probe["dimension"])
        self.ready = True

    def health(self) -> dict[str, Any]:
        cuda_available = bool(self.torch and self.torch.cuda.is_available())
        allocated = None
        reserved = None
        if cuda_available:
            allocated = int(self.torch.cuda.memory_allocated(0))
            reserved = int(self.torch.cuda.memory_reserved(0))

        status = "ready" if self.ready else "loading"
        if self.load_error:
            status = "error"
        elif self.skip_model_load and not self.ready:
            status = "test"

        return {
            "status": status,
            "ready": self.ready,
            "model": self.model_name,
            "device": self.device,
            "dtype": self.dtype_name,
            "cuda_available": cuda_available,
            "gpu_name": self.gpu_name,
            "total_vram_bytes": self.total_vram_bytes,
            "allocated_vram_bytes": allocated,
            "reserved_vram_bytes": reserved,
            "embedding_dimension": self.embedding_dimension,
            "max_image_edge": self.max_image_edge,
            "error": self.load_error,
        }

    def _ensure_ready(self) -> None:
        if not self.ready or self.model is None or self.processor is None:
            detail = self.load_error or "ColSmol model is not ready"
            raise RuntimeError(detail)

    def _serialize(self, tensor: Any) -> dict[str, Any]:
        vectors = tensor[0].detach().float().cpu()
        vector_count = int(vectors.shape[0])
        dimension = int(vectors.shape[1])
        return {
            "vectors": vectors.tolist(),
            "vector_count": vector_count,
            "dimension": dimension,
            "model": self.model_name,
        }

    def embed_query(self, text: str) -> dict[str, Any]:
        self._ensure_ready()
        with self._lock, self.torch.inference_mode():
            batch = self.processor.process_queries([text]).to(self.device)
            embeddings = self.model(**batch)
            return self._serialize(embeddings)

    def embed_image(self, image: Image.Image) -> dict[str, Any]:
        self._ensure_ready()
        with self._lock, self.torch.inference_mode():
            batch = self.processor.process_images([image]).to(self.device)
            embeddings = self.model(**batch)
            return self._serialize(embeddings)

    def decode_image(self, payload: bytes) -> Image.Image:
        try:
            image = Image.open(io.BytesIO(payload))
            image.load()
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("Uploaded file is not a readable image") from exc

        image = image.convert("RGB")
        largest_edge = max(image.size)
        if largest_edge > self.max_image_edge:
            scale = self.max_image_edge / largest_edge
            resized = (
                max(1, round(image.width * scale)),
                max(1, round(image.height * scale)),
            )
            image = image.resize(resized, Image.Resampling.LANCZOS)
        return image


runtime = ColSmolRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    try:
        runtime.load()
    except Exception as exc:  # Keep health endpoint alive for actionable diagnostics.
        runtime.load_error = str(exc)
    yield


app = FastAPI(
    title="Construction OS ColSmol Service",
    version="0.1.0",
    lifespan=lifespan,
)


@app.get("/health")
def health() -> dict[str, Any]:
    return runtime.health()


@app.post("/embed/query")
def embed_query(body: QueryRequest) -> dict[str, Any]:
    try:
        return runtime.embed_query(body.text.strip())
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/embed/image")
def embed_image(file: UploadFile = File(...)) -> dict[str, Any]:
    payload = file.file.read(runtime.max_upload_bytes + 1)
    if len(payload) > runtime.max_upload_bytes:
        raise HTTPException(status_code=413, detail="Image upload exceeds configured limit")
    try:
        image = runtime.decode_image(payload)
        result = runtime.embed_image(image)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    result["image_width"] = image.width
    result["image_height"] = image.height
    return result
