"""Shared OpenCLIP encoder. When unavailable, callers degrade to non-CLIP signals."""
from __future__ import annotations

import logging
import threading

import cv2
import numpy as np
from PIL import Image

from app.config import settings
from app.cv.device import active_device

logger = logging.getLogger(__name__)
LOGIT_SCALE = 100.0


class ClipService:
    def __init__(self) -> None:
        self.model = None
        self.error: str | None = None
        self.device = "cpu"
        self._text_cache: dict[str, np.ndarray] = {}
        self._lock = threading.Lock()
        try:
            import open_clip
            import torch

            self.torch = torch
            self.device = active_device()
            model, _, preprocess = open_clip.create_model_and_transforms(
                settings.clip_model, pretrained=settings.clip_pretrained
            )
            self.model = model.to(self.device).eval()
            self.preprocess = preprocess
            self.tokenizer = open_clip.get_tokenizer(settings.clip_model)
        except Exception as error:  # Weight download failures must not stop the pipeline.
            self.error = f"{type(error).__name__}: {error}"
            self.model = None
            logger.warning("OpenCLIP unavailable: %s", error)

    @property
    def available(self) -> bool:
        return self.model is not None

    def encode_images(self, crops: list[np.ndarray]) -> np.ndarray:
        images = [self.preprocess(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB))) for crop in crops]
        batch = self.torch.stack(images).to(self.device)
        with self._lock, self.torch.no_grad():
            features = self.model.encode_image(batch)
            features = features / features.norm(dim=-1, keepdim=True)
        return features.cpu().numpy()

    def encode_prompts(self, prompts: list[str]) -> np.ndarray:
        missing = [prompt for prompt in prompts if prompt not in self._text_cache]
        if missing:
            tokens = self.tokenizer(missing).to(self.device)
            with self._lock, self.torch.no_grad():
                features = self.model.encode_text(tokens)
                features = features / features.norm(dim=-1, keepdim=True)
            for prompt, vector in zip(missing, features.cpu().numpy()):
                self._text_cache[prompt] = vector
        return np.stack([self._text_cache[prompt] for prompt in prompts])

    def zero_shot(self, image_embedding: np.ndarray, prompt_groups: list[list[str]]) -> np.ndarray:
        """Softmax over classes, with each class represented by its mean prompt embedding."""
        classes = []
        for prompts in prompt_groups:
            mean = self.encode_prompts(prompts).mean(axis=0)
            classes.append(mean / np.linalg.norm(mean))
        logits = LOGIT_SCALE * (np.stack(classes) @ image_embedding)
        logits -= logits.max()
        probabilities = np.exp(logits)
        return probabilities / probabilities.sum()
