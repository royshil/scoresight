"""PaddleOCR text recognition models (PP-OCRv6, PP-OCRv5) on onnxruntime.

Only the recognition model is used: a ScoreSight box already is the text line,
so there is no detection step. The models are the official ONNX exports on the
Hugging Face Hub (PaddlePaddle/*_rec_onnx, Apache-2.0), downloaded at a pinned
revision into the Hugging Face cache on first use. They are run directly with
onnxruntime, without PaddleOCR or RapidOCR, so that the CTC output can be
decoded here: unconstrained, or limited to the box's characters.

Preprocessing is PaddleOCR's for these models (the model's inference.yml:
RecResizeImg image_shape [3, 48, 320], BGR input): the crop is resized to 48 px
high keeping its aspect ratio, scaled to [-1, 1] ((x / 255 - 0.5) / 0.5) and
padded on the right with zeros to at least 320 px (6.67:1). PaddleOCR pads a
batch to its widest crop; here crops are grouped by their own padded width, so
a crop's reading never depends on the other crops in its batch.

Decoding is greedy CTC (PaddleOCR's CTCLabelDecode): the classes are blank,
the model's character dictionary and a space; repeats are merged and blanks
dropped, and the confidence is the mean probability of the kept characters.

Variants: <model>[-bin|-gray][-wl]
  model   v6-tiny, v6-small, v6-medium (PP-OCRv6, June 2026), v5-mobile,
          v5-server (PP-OCRv5, multilingual) and v5-en-mobile (PP-OCRv5,
          English dictionary)
  -bin    the crop is first binarized the way ScoreSight prepares a box for
          Tesseract (src/tesseract.py preprocess_patch with the field type's
          default box settings: Otsu over the crop, dilate 1), without
          Tesseract's rescale to 35 px
  -gray   the crop in gray (in all three channels), as ScoreSight's capture
          thread converts the frame before OCR (camera_thread.to_gray)
          otherwise the raw colour crop
  -wl     decoding is limited to the characters of the field type's box
          (ocr_eval.fields.whitelist): at every time step the blank competes
          only with the allowed characters, and dictionary characters that are
          the same under NFKC (e.g. full-width digits) count as one; otherwise
          the unconstrained reading. info["free"] keeps the unconstrained
          reading when it differs.
"--engine ppocr" runs every model except v5-server on the raw crop, with and
without -wl. v5-server is left out because it is impractically slow on
onnxruntime's CPU provider (about 0.6 s per crop on all cores and 3 s on one
thread, nearly all of it in its convolutions); ask for it by name.

Set OCR_EVAL_ORT_THREADS to the number of onnxruntime intra-op threads (default
1, comparable with Tesseract's single thread; 0 lets onnxruntime choose), and
OCR_EVAL_ORT_SPINNING=0 to let idle pool threads sleep instead of busy-waiting
(onnxruntime's default spinning costs CPU time with more than one thread).
Predictions don't depend on either.
"""

import importlib.metadata
import math
import os
import unicodedata
from dataclasses import dataclass

import cv2
import numpy as np

from ocr_eval._src import isolate_app_state
from ocr_eval.engines import Engine, EngineUnavailable, Recognition
from ocr_eval.fields import box_settings, whitelist

# huggingface_hub 1.x: OnnxTR 0.9.0 requires < 2, and requirements-eval.txt
# installs every engine's extras together
REQUIREMENTS: list[str] = [
    "onnxruntime==1.31.1",
    "huggingface_hub==1.33.0",
    "PyYAML==6.0.3",
]


@dataclass(frozen=True)
class RecModel:
    repo: str
    revision: str
    size: str
    description: str


MODELS: dict[str, RecModel] = {
    "v6-tiny": RecModel(
        "PaddlePaddle/PP-OCRv6_tiny_rec_onnx",
        "2612ab37152ae0a677521bae4e1e3d4fb4cf7c30",
        "1.1M parameters, 4.5 MB",
        "PP-OCRv6 tiny (LCNetV4, CTC), 49 languages",
    ),
    "v6-small": RecModel(
        "PaddlePaddle/PP-OCRv6_small_rec_onnx",
        "b8f84f0b80c529de40b4fbb3544b84fa7233a513",
        "5.2M parameters, 21 MB",
        "PP-OCRv6 small (LCNetV4 + LightSVTR, CTC), 50 languages",
    ),
    "v6-medium": RecModel(
        "PaddlePaddle/PP-OCRv6_medium_rec_onnx",
        "50c7eacafc52fa7bcf4194e8cd08e46f8558504b",
        "19M parameters, 77 MB",
        "PP-OCRv6 medium (LCNetV4 + LightSVTR, CTC), 50 languages",
    ),
    "v5-mobile": RecModel(
        "PaddlePaddle/PP-OCRv5_mobile_rec_onnx",
        "ed152b8b495f84de93cda5709d768548a9127622",
        "17 MB",
        "PP-OCRv5 mobile (CTC), Chinese, English and Japanese",
    ),
    "v5-en-mobile": RecModel(
        "PaddlePaddle/en_PP-OCRv5_mobile_rec_onnx",
        "3fafbc3b5dcf93dd72add9f48368be8a3a2cd33b",
        "7.8 MB",
        "PP-OCRv5 mobile (CTC), English dictionary (436 characters)",
    ),
    "v5-server": RecModel(
        "PaddlePaddle/PP-OCRv5_server_rec_onnx",
        "b70df217f4fd99d14f970bad092cebe7d74cc4d1",
        "85 MB",
        "PP-OCRv5 server (CTC), Chinese, English and Japanese",
    ),
}
# not run by "--engine ppocr" (see the module docstring)
SLOW_MODELS = ("v5-server",)
BIN_SUFFIX = "-bin"
GRAY_SUFFIX = "-gray"
WHITELIST_SUFFIX = "-wl"
THREADS_ENV = "OCR_EVAL_ORT_THREADS"
SPINNING_ENV = "OCR_EVAL_ORT_SPINNING"

# PaddleOCR's recognition input when inference.yml doesn't say otherwise
DEFAULT_IMAGE_SHAPE = (3, 48, 320)


def split_variant(variant: str) -> tuple[str, str, bool]:
    """'v6-tiny-bin-wl' -> ('v6-tiny', preprocessing='-bin', whitelist=True);
    the preprocessing is '' (the colour crop), '-bin' or '-gray'."""
    constrained = variant.endswith(WHITELIST_SUFFIX)
    if constrained:
        variant = variant[: -len(WHITELIST_SUFFIX)]
    for suffix in (BIN_SUFFIX, GRAY_SUFFIX):
        if variant.endswith(suffix):
            return variant[: -len(suffix)], suffix, constrained
    return variant, "", constrained


def _variant_names() -> tuple[str, ...]:
    return tuple(
        f"{model}{prep}{dec}"
        for prep in ("", BIN_SUFFIX, GRAY_SUFFIX)
        for dec in ("", WHITELIST_SUFFIX)
        for model in MODELS
    )


# ---------------------------------------------------------------------------
# Preprocessing and decoding (numpy only, so they can be tested without models)


def padded_width(height: int, width: int, image_height: int, min_width: int) -> int:
    """The input width PaddleOCR gives a crop of this size on its own: the
    resized width, at least min_width."""
    ratio = width / max(1, height)
    return max(min_width, int(image_height * ratio))


def resize_normalize(
    image: np.ndarray, image_height: int, target_width: int
) -> np.ndarray:
    """PaddleOCR's resize_norm_img: (3, image_height, target_width) float32,
    the crop resized to image_height keeping its aspect ratio (at most
    target_width wide), scaled to [-1, 1] and padded with zeros on the right."""
    height, width = image.shape[:2]
    ratio = width / max(1, height)
    resized_width = max(1, min(target_width, math.ceil(image_height * ratio)))
    resized = cv2.resize(image, (resized_width, image_height))
    resized = resized.astype(np.float32).transpose(2, 0, 1) / 255.0
    resized = (resized - 0.5) / 0.5
    padded = np.zeros((3, image_height, target_width), dtype=np.float32)
    padded[:, :, :resized_width] = resized
    return padded


def as_probabilities(output: np.ndarray) -> np.ndarray:
    """The exported models end with a softmax; apply one if a model doesn't."""
    sums = output.sum(axis=-1)
    if output.min() >= 0.0 and np.allclose(sums, 1.0, atol=1e-3):
        return output
    shifted = output - output.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def ctc_greedy(
    probs: np.ndarray, labels: list[str]
) -> tuple[str, float | None, np.ndarray]:
    """Greedy CTC decoding of one (time, classes) probability matrix whose
    class 0 is the blank: the best class per step, repeats merged, blanks
    dropped. Returns the text, the mean probability of the kept steps (None if
    nothing is kept) and the kept class indices."""
    best = probs.argmax(axis=1)
    keep = best != 0
    keep[1:] &= best[1:] != best[:-1]
    kept = best[keep]
    text = "".join(labels[i] for i in kept)
    if kept.size == 0:
        return text, None, kept
    confidence = float(probs[np.flatnonzero(keep), kept].mean())
    return text, confidence, kept


@dataclass
class ClassGroups:
    """The classes a field type's box allows, grouped by what they read as."""

    labels: list[str]  # "" (blank) then the output string of each group
    columns: np.ndarray  # class indices, group after group
    starts: np.ndarray  # where each group starts in columns

    def reduce(self, probs: np.ndarray) -> np.ndarray:
        """(time, classes) -> (time, 1 + groups): the blank, then the summed
        probability of each group's classes."""
        grouped = np.add.reduceat(probs[:, self.columns], self.starts, axis=1)
        return np.concatenate([probs[:, :1], grouped], axis=1)


def class_groups(characters: list[str], allowed: str) -> ClassGroups:
    """Group the model's classes (characters[0] is the blank) whose NFKC form
    is made only of allowed characters by that form. Everything else can't be
    output."""
    groups: dict[str, list[int]] = {}
    for index, char in enumerate(characters):
        if index == 0:
            continue
        form = unicodedata.normalize("NFKC", char)
        if form and all(c in allowed for c in form):
            groups.setdefault(form, []).append(index)
    labels = [""]
    columns: list[int] = []
    starts: list[int] = []
    for form, indices in groups.items():
        labels.append(form)
        starts.append(len(columns))
        columns.extend(indices)
    if not columns:
        raise ValueError(f"the model has none of the characters {allowed!r}")
    return ClassGroups(labels, np.array(columns), np.array(starts))


def read_character_dict(config: dict) -> list[str]:
    """The classes of a PaddleOCR CTC recognition model from its inference.yml:
    the blank, the dictionary and a space (CTCLabelDecode, use_space_char)."""
    post = config.get("PostProcess") or {}
    if post.get("name") != "CTCLabelDecode":
        raise ValueError(f"not a CTC model (PostProcess {post.get('name')!r})")
    dictionary = post.get("character_dict")
    if not dictionary or not all(isinstance(c, str) and c for c in dictionary):
        raise ValueError("inference.yml has no usable character_dict")
    return ["", *dictionary, " "]


def read_input_config(config: dict) -> tuple[int, int, str]:
    """(height, minimum width, channel order) of the model's input."""
    shape = DEFAULT_IMAGE_SHAPE
    mode = "BGR"
    for op in (config.get("PreProcess") or {}).get("transform_ops") or []:
        if not isinstance(op, dict):
            continue
        if "RecResizeImg" in op:
            shape = tuple(op["RecResizeImg"]["image_shape"])
        if "DecodeImage" in op:
            mode = (op["DecodeImage"] or {}).get("img_mode", mode)
    if len(shape) != 3 or shape[0] != 3:
        raise ValueError(f"unexpected input shape {shape}")
    return int(shape[1]), int(shape[2]), mode


# ---------------------------------------------------------------------------


class PaddleOCRRec(Engine):
    name = "ppocr"
    variants = _variant_names()
    # every model but the slow v5-server on the raw crop, unconstrained and
    # limited to the box's characters; "ppocr:*" runs everything
    default_variants = tuple(
        f"{m}{dec}"
        for dec in ("", WHITELIST_SUFFIX)
        for m in MODELS
        if m not in SLOW_MODELS
    )
    description = (
        "PaddleOCR PP-OCRv6/PP-OCRv5 text recognition (ONNX), greedy CTC "
        "decoding, unconstrained or limited to the box's characters"
    )
    size = "1.1M-21M parameters, 4.5-85 MB"
    license = "Apache-2.0"
    runtime = "onnxruntime, CPU"
    imports = ("onnxruntime", "huggingface_hub", "yaml")
    batch_size = 16

    def __init__(self, variant: str | None = None):
        super().__init__(variant)
        self.model_key, self.preprocessing, self.constrained = split_variant(
            self.variant
        )
        self.binarize = self.preprocessing == BIN_SUFFIX
        self.gray = self.preprocessing == GRAY_SUFFIX
        self.model = MODELS[self.model_key]
        self._session = None
        self._input_name = None
        self._characters: list[str] = []
        self._image_height, self._min_width = DEFAULT_IMAGE_SHAPE[1:]
        self._rgb = False
        self._groups: dict[str, ClassGroups] = {}
        self._settings: dict[str, dict] = {}
        self._preprocess_patch = None
        self._global_binarization = None
        self._threads = _threads()
        self._spinning = os.environ.get(SPINNING_ENV, "").strip() != "0"

    # -- loading

    def pinned_files(self) -> list[tuple[str, str, str]]:
        """The model's files on the Hugging Face Hub: (repository, pinned
        revision, file name). python -m ocr_eval.fetch_models downloads them."""
        return [
            (self.model.repo, self.model.revision, name)
            for name in ("inference.onnx", "inference.yml")
        ]

    def model_files(self) -> tuple[str, str]:
        """Download (or find in the Hugging Face cache) the model's ONNX file
        and its inference.yml at the pinned revision."""
        from huggingface_hub import hf_hub_download

        try:
            return tuple(
                hf_hub_download(repo, name, revision=revision)
                for repo, revision, name in self.pinned_files()
            )
        except Exception as e:
            raise EngineUnavailable(
                f"can't get {self.model.repo}@{self.model.revision[:8]} from the "
                f"Hugging Face Hub: {type(e).__name__}: {e}"
            ) from e

    @staticmethod
    def read_config(config_path: str) -> dict:
        import yaml

        with open(config_path, encoding="utf-8") as f:
            return yaml.safe_load(f)

    def create_session(self, onnx_path: str):
        import onnxruntime

        options = onnxruntime.SessionOptions()
        options.log_severity_level = 3  # the exports have unused initializers
        if self._threads:
            options.intra_op_num_threads = self._threads
            options.inter_op_num_threads = 1
        if not self._spinning:
            # idle pool threads sleep instead of busy-waiting for work
            options.add_session_config_entry("session.intra_op.allow_spinning", "0")
        return onnxruntime.InferenceSession(
            onnx_path, options, providers=["CPUExecutionProvider"]
        )

    def load(self) -> None:
        onnx_path, config_path = self.model_files()
        config = self.read_config(config_path)
        self._characters = read_character_dict(config)
        self._image_height, self._min_width, mode = read_input_config(config)
        self._rgb = mode.upper() == "RGB"
        self._session = self.create_session(onnx_path)
        self._input_name = self._session.get_inputs()[0].name
        classes = self._session.get_outputs()[0].shape[-1]
        if isinstance(classes, int) and classes != len(self._characters):
            raise RuntimeError(
                f"{self.model.repo}: the model has {classes} classes but its "
                f"dictionary gives {len(self._characters)}"
            )
        if self.binarize:
            isolate_app_state()
            try:
                # ScoreSight's src/tesseract.py (needs tesserocr and PySide6)
                from tesseract import global_binarization, preprocess_patch
            except ImportError as e:
                raise EngineUnavailable(
                    f"the -bin variants need ScoreSight's tesseract module: {e}"
                ) from e
            self._preprocess_patch = preprocess_patch
            self._global_binarization = global_binarization

    # -- recognition

    def _prepare(self, crop: np.ndarray, field_type: str) -> np.ndarray:
        if self.binarize:
            settings = self._settings.get(field_type)
            if settings is None:
                settings = self._settings[field_type] = box_settings(field_type)
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            height, width = gray.shape[:2]
            patch = self._preprocess_patch(
                settings,
                (0, 0, width, height),
                gray,
                lambda: self._global_binarization(gray),
            )
            if settings.get("invert_patch"):
                patch = 255 - patch
            return cv2.cvtColor(patch, cv2.COLOR_GRAY2BGR)
        if self.gray:
            gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
            return cv2.cvtColor(gray, cv2.COLOR_GRAY2BGR)
        if self._rgb:
            return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        return crop

    def _groups_for(self, field_type: str) -> ClassGroups:
        groups = self._groups.get(field_type)
        if groups is None:
            groups = self._groups[field_type] = class_groups(
                self._characters, whitelist(field_type)
            )
        return groups

    def _decode(self, probs: np.ndarray, field_type: str) -> Recognition:
        text, confidence, _ = ctc_greedy(probs, self._characters)
        if not self.constrained:
            return Recognition(text, _round(confidence))
        groups = self._groups_for(field_type)
        constrained, confidence, _ = ctc_greedy(groups.reduce(probs), groups.labels)
        info = {"free": text} if text != constrained else None
        return Recognition(constrained, _round(confidence), info)

    def recognize(self, crops, field_types):
        images = [self._prepare(c, ft) for c, ft in zip(crops, field_types)]
        widths = [
            padded_width(
                image.shape[0], image.shape[1], self._image_height, self._min_width
            )
            for image in images
        ]
        results: list[Recognition | None] = [None] * len(images)
        # one session call per padded width, so that a crop is read the same
        # way whatever else is in the batch
        for width in sorted(set(widths)):
            indices = [i for i, w in enumerate(widths) if w == width]
            batch = np.stack(
                [
                    resize_normalize(images[i], self._image_height, width)
                    for i in indices
                ]
            )
            [output] = self._session.run(None, {self._input_name: batch})
            probs = as_probabilities(np.asarray(output, dtype=np.float32))
            if probs.shape[-1] != len(self._characters):
                raise RuntimeError(
                    f"{probs.shape[-1]} classes for a dictionary of "
                    f"{len(self._characters)}"
                )
            for row, i in enumerate(indices):
                results[i] = self._decode(probs[row], field_types[i])
        return results

    def close(self) -> None:
        self._session = None

    def info(self) -> dict:
        info = super().info()
        info.update(
            description=self.model.description,
            size=self.model.size,
            model=self.model.repo,
            revision=self.model.revision,
            preprocessing={
                BIN_SUFFIX: "ScoreSight binarization (preprocess_patch, field "
                "type's box settings)",
                GRAY_SUFFIX: "the crop in gray (ScoreSight's to_gray)",
            }.get(self.preprocessing, "raw crop"),
            decoding="field type's whitelist" if self.constrained else "unconstrained",
            input=f"{self._image_height} px high, padded to at least {self._min_width} px",
            intra_op_threads=self._threads or "onnxruntime default",
            intra_op_spinning=self._spinning,
        )
        try:
            info["version"] = f"onnxruntime {importlib.metadata.version('onnxruntime')}"
        except importlib.metadata.PackageNotFoundError:
            pass
        return info


def _round(confidence: float | None) -> float | None:
    return None if confidence is None else round(confidence, 4)


def _threads() -> int:
    value = os.environ.get(THREADS_ENV, "").strip()
    if not value:
        return 1
    try:
        return max(0, int(value))
    except ValueError:
        raise ValueError(f"{THREADS_ENV} must be a whole number, not {value!r}")
