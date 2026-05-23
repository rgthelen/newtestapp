"""Config loader. Merges defaults + ~/.config/pi5-hailo-vision/{app,cameras}.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


def _expand(p: str | os.PathLike[str]) -> Path:
    return Path(os.path.expanduser(os.path.expandvars(str(p)))).resolve()


def _config_dir() -> Path:
    return _expand(os.environ.get("PI5_VISION_CONFIG_DIR", "~/.config/pi5-hailo-vision"))


@dataclass
class DetectConfig:
    enabled: bool = True
    min_confidence: float = 0.4
    classes: list[str] = field(default_factory=list)


@dataclass
class TrackConfig:
    enabled: bool = True
    max_age: int = 30
    min_hits: int = 3


@dataclass
class ClipIndexConfig:
    enabled: bool = True
    every_n_frames: int = 30
    only_when_tracking: bool = True
    bbox_padding: float = 0.15
    # Hard rate-limit per track id, in seconds. A track is always embedded
    # the first time we see it; thereafter we wait this long before
    # re-embedding it, no matter how often `every_n_frames` fires.
    min_seconds_between_embeds_per_track: float = 5.0


@dataclass
class CameraConfig:
    id: str
    name: str
    url: str
    transport: str = "tcp"
    fps: int = 15
    resolution: tuple[int, int] | None = None
    detect: DetectConfig = field(default_factory=DetectConfig)
    track: TrackConfig = field(default_factory=TrackConfig)
    clip_index: ClipIndexConfig = field(default_factory=ClipIndexConfig)


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080


@dataclass
class Paths:
    models_dir: Path = _expand("~/.local/share/pi5-hailo-vision/models")
    snapshots_dir: Path = _expand("~/.local/share/pi5-hailo-vision/snapshots")
    db_path: Path = _expand("~/.local/share/pi5-hailo-vision/events.db")
    log_dir: Path = _expand("~/.local/state/pi5-hailo-vision/logs")


@dataclass
class YoloModelConfig:
    hef: str = "yolov11s.hef"
    input_size: tuple[int, int] = (640, 640)


@dataclass
class ClipModelConfig:
    # Defaults: openai/clip-vit-base-patch16 (ViT-B/16). Both image and text
    # encoders run on Hailo as HEFs. 512-d shared embedding space.
    # If you change one HEF, change the matching pair AND the tokenizer.
    image_hef: str = "clip_vit_base_patch16_image.hef"
    image_input_size: tuple[int, int] = (224, 224)
    text_hef: str = "clip_vit_base_patch16_text.hef"
    text_tokenizer: str = "clip_tokenizer.json"
    embedding_dim: int = 512


@dataclass
class ModelsConfig:
    yolo: YoloModelConfig = field(default_factory=YoloModelConfig)
    clip: ClipModelConfig = field(default_factory=ClipModelConfig)


@dataclass
class RetentionConfig:
    snapshot_days: int = 14
    event_days: int = 30


@dataclass
class AppConfig:
    server: ServerConfig = field(default_factory=ServerConfig)
    paths: Paths = field(default_factory=Paths)
    models: ModelsConfig = field(default_factory=ModelsConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    cameras: list[CameraConfig] = field(default_factory=list)


def _load_yaml(p: Path) -> dict[str, Any]:
    if not p.exists():
        return {}
    with p.open() as f:
        return yaml.safe_load(f) or {}


def _coerce_camera(raw: dict[str, Any]) -> CameraConfig:
    detect = DetectConfig(**(raw.get("detect") or {}))
    track = TrackConfig(**(raw.get("track") or {}))
    clip_idx = ClipIndexConfig(**(raw.get("clip_index") or {}))
    return CameraConfig(
        id=raw["id"],
        name=raw.get("name", raw["id"]),
        url=raw["url"],
        transport=raw.get("transport", "tcp"),
        fps=int(raw.get("fps", 15)),
        resolution=tuple(raw["resolution"]) if raw.get("resolution") else None,
        detect=detect,
        track=track,
        clip_index=clip_idx,
    )


def load_config() -> AppConfig:
    cfg_dir = _config_dir()
    app_yaml = _load_yaml(cfg_dir / "app.yaml")
    cam_yaml = _load_yaml(cfg_dir / "cameras.yaml")

    cfg = AppConfig()

    if srv := app_yaml.get("server"):
        cfg.server = ServerConfig(**srv)

    if paths := app_yaml.get("paths"):
        cfg.paths = Paths(
            models_dir=_expand(paths.get("models_dir", cfg.paths.models_dir)),
            snapshots_dir=_expand(paths.get("snapshots_dir", cfg.paths.snapshots_dir)),
            db_path=_expand(paths.get("db_path", cfg.paths.db_path)),
            log_dir=_expand(paths.get("log_dir", cfg.paths.log_dir)),
        )

    if models := app_yaml.get("models"):
        if yolo := models.get("yolo"):
            cfg.models.yolo = YoloModelConfig(
                hef=yolo.get("hef", cfg.models.yolo.hef),
                input_size=tuple(yolo.get("input_size", cfg.models.yolo.input_size)),
            )
        if clip := models.get("clip"):
            cfg.models.clip = ClipModelConfig(
                image_hef=clip.get("image_hef", cfg.models.clip.image_hef),
                image_input_size=tuple(
                    clip.get("image_input_size", cfg.models.clip.image_input_size)
                ),
                text_hef=clip.get("text_hef", cfg.models.clip.text_hef),
                text_tokenizer=clip.get("text_tokenizer", cfg.models.clip.text_tokenizer),
                embedding_dim=int(clip.get("embedding_dim", cfg.models.clip.embedding_dim)),
            )

    if ret := app_yaml.get("retention"):
        cfg.retention = RetentionConfig(**ret)

    cfg.cameras = [_coerce_camera(c) for c in (cam_yaml.get("cameras") or [])]

    # Ensure runtime paths exist.
    for p in (cfg.paths.snapshots_dir, cfg.paths.log_dir, cfg.paths.db_path.parent):
        p.mkdir(parents=True, exist_ok=True)

    return cfg
