"""명시적으로 요청할 때만 실제 PP-StructureV3 모델을 실행한다."""

import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.adapters.parsers.paddle_structure import PPStructureV3Adapter
from app.core.config import Settings

pytestmark = pytest.mark.paddle_integration


@pytest.mark.skipif(
    os.getenv("RUN_PADDLEOCR_INTEGRATION_TESTS") != "1",
    reason="Set RUN_PADDLEOCR_INTEGRATION_TESTS=1 to run real model inference.",
)
async def test_real_paddleocr_smoke(tmp_path: Path) -> None:
    image_module = pytest.importorskip("PIL.Image")
    input_path = tmp_path / "simple.png"
    image_module.new("RGB", (320, 120), color="white").save(input_path)
    settings = Settings(
        _env_file=None,
        paddleocr_enabled=True,
        paddleocr_device=os.getenv("PADDLEOCR_DEVICE", "cpu"),
        paddleocr_model_cache_dir=os.getenv("PADDLEOCR_MODEL_CACHE_DIR") or None,
    )
    adapter = PPStructureV3Adapter(
        SimpleNamespace(name="PaddleOCR PP-StructureV3", model_version="3.7.0"),
        settings=settings,
    )

    result = await adapter.parse(input_path, tmp_path, {})

    assert result.raw_data["document"]["page_count"] >= 1
    assert isinstance(result.raw_data["content"]["pages"][0]["raw"], dict)
    assert isinstance(result.markdown, str)
