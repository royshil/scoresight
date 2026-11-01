"""docTR's text recognizers, run with ONNX Runtime through OnnxTR.

OnnxTR (https://github.com/felixdittrich92/OnnxTR) ships ONNX exports of docTR's
pretrained word recognizers (Apache-2.0). They read one cropped word per image,
resized to 32 x 128 with its aspect ratio kept, over docTR's "french" vocabulary:
digits, ASCII letters and punctuation, the degree sign, currency signs and
French accented letters (no space). Models:

  parseq                   PARSeq, autoregressive attention decoder (23.8M params)
  crnn_mobilenet_v3_small  CRNN with a MobileNetV3-small backbone, CTC (2.1M)
  viptr_tiny               VIPTR-tiny, CTC (3.3M)
  vitstr_small             ViTSTR-small, parallel attention decoder (21.4M)
  <model>-int8             OnnxTR's 8-bit quantized export of the model (not run
                           by `--engine onnxtr`; viptr_tiny has none)

Variant suffixes (preprocessing and decoding):

  (none)   the raw colour crop (converted to RGB, as docTR's models expect)
  -wl      the same, with decoding restricted to the field type's character
           whitelist (ocr_eval.fields.whitelist) plus the end/blank token. Exact
           for the CTC models and ViTSTR, whose outputs are per position. PARSeq
           decodes greedily and autoregressively inside its ONNX graph (one
           ArgMax per position), so its later positions were predicted from the
           unrestricted earlier ones and the restriction only applies to the
           final choice at each position.
  -bin     ScoreSight's preprocessing first: the image TextDetector would give
           Tesseract for a box covering the crop, with the field type's default
           box settings (Otsu binarization of the crop, dilate, rescale to 35 px
           tall). A blank patch (nothing left after binarization) is not read,
           as in ScoreSight.
  -bin-wl  both.

Confidence: OnnxTR's (the mean probability of the characters for the attention
models, the lowest per-frame probability for CTC); for -wl, the same computed
for the restricted reading over the model's unrestricted probabilities. When
-wl changes a reading, info["unrestricted"] holds the unrestricted one.

ONNX Runtime runs on the CPU only (no CUDA or CoreML, for comparable numbers)
with its default thread pool; set OCR_EVAL_ONNX_THREADS to a number of threads
to measure e.g. single-thread latency. Models are downloaded on first use to
OnnxTR's cache (~/.cache/onnxtr, or $ONNXTR_CACHE_DIR).
"""

import importlib.metadata
import os
from pathlib import Path
from typing import NamedTuple

import cv2
import numpy as np

from ocr_eval._src import isolate_app_state
from ocr_eval.engines import Engine, EngineUnavailable, Recognition
from ocr_eval.fields import FIELD_TYPES, box_settings, whitelist

REQUIREMENTS: list[str] = ["onnxtr[cpu-headless]==0.9.0", "onnxruntime==1.31.1"]

THREADS_ENV = "OCR_EVAL_ONNX_THREADS"


class Model(NamedTuple):
    arch: str  # the OnnxTR architecture name
    int8: bool  # OnnxTR's 8-bit quantized export
    decoder: str  # "ctc" or "attention"
    description: str
    params: str  # parameters (the fp32 ONNX graph's initializers)


MODELS = {
    "parseq": Model(
        "parseq",
        False,
        "attention",
        "PARSeq (permuted autoregressive sequence model)",
        "23.8M",
    ),
    "crnn_mobilenet_v3_small": Model(
        "crnn_mobilenet_v3_small",
        False,
        "ctc",
        "CRNN with a MobileNetV3-small backbone, CTC",
        "2.1M",
    ),
    "viptr_tiny": Model(
        "viptr_tiny",
        False,
        "ctc",
        "VIPTR-tiny (vision permutable extractor), CTC",
        "3.3M",
    ),
    "vitstr_small": Model(
        "vitstr_small",
        False,
        "attention",
        "ViTSTR-small (vision transformer, parallel decoding)",
        "21.4M",
    ),
    "parseq-int8": Model(
        "parseq",
        True,
        "attention",
        "PARSeq, 8-bit dynamic quantization",
        "23.8M",
    ),
    "crnn_mobilenet_v3_small-int8": Model(
        "crnn_mobilenet_v3_small",
        True,
        "ctc",
        "CRNN MobileNetV3-small, 8-bit static quantization",
        "2.1M",
    ),
    "vitstr_small-int8": Model(
        "vitstr_small",
        True,
        "attention",
        "ViTSTR-small, 8-bit dynamic quantization",
        "21.4M",
    ),
}

# variant suffix -> (ScoreSight preprocessing, whitelist-restricted decoding)
SUFFIXES = {
    "": (False, False),
    "-wl": (False, True),
    "-bin": (True, False),
    "-bin-wl": (True, True),
}


def split_variant(variant: str) -> tuple[str, str]:
    """'parseq-int8-bin-wl' -> ('parseq-int8', '-bin-wl')."""
    for suffix in sorted(SUFFIXES, key=len, reverse=True):
        if suffix and variant.endswith(suffix) and variant[: -len(suffix)] in MODELS:
            return variant[: -len(suffix)], suffix
    return variant, ""


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits.astype(np.float64) - logits.max(axis=-1, keepdims=True)
    exp = np.exp(shifted)
    return exp / exp.sum(axis=-1, keepdims=True)


def allowed_classes(vocab: str, chars: str) -> np.ndarray:
    """A boolean mask over a model's output classes (the vocabulary, then the
    CTC blank or the <eos> token, which is always allowed): the vocabulary
    characters that are in chars."""
    allowed = np.zeros(len(vocab) + 1, dtype=bool)
    for index, char in enumerate(vocab):
        allowed[index] = char in chars
    allowed[len(vocab)] = True
    return allowed


def _best(logits: np.ndarray, allowed: np.ndarray | None) -> np.ndarray:
    if allowed is None:
        return logits.argmax(axis=-1)
    classes = logits.shape[-1]
    mask = np.zeros(classes, dtype=bool)
    mask[: min(classes, len(allowed))] = allowed[:classes]
    return np.where(mask, logits, -np.inf).argmax(axis=-1)


def decode_ctc(
    logits: np.ndarray, vocab: str, allowed: np.ndarray | None = None
) -> tuple[str, float]:
    """Greedy (best path) CTC decoding of one crop's logits (frames x classes,
    blank = len(vocab)), as OnnxTR's CRNN and VIPTR post-processors do; with
    allowed, the best path through the allowed classes only. The confidence is
    the lowest probability of the chosen class over the frames."""
    if logits.shape[0] == 0:
        return "", 0.0
    best = _best(logits, allowed)
    probabilities = _softmax(logits)[np.arange(len(best)), best]
    blank = len(vocab)
    chars = []
    previous = None
    for index in best.tolist():
        if index != previous and index != blank:
            chars.append(vocab[index])
        previous = index
    return "".join(chars), float(probabilities.min())


def decode_attention(
    logits: np.ndarray, vocab: str, allowed: np.ndarray | None = None
) -> tuple[str, float]:
    """Greedy decoding of one crop's attention-decoder logits (positions x
    classes, <eos> = len(vocab)): the most likely class at each position, up
    to the first <eos>, as OnnxTR's PARSeq and ViTSTR post-processors do; with
    allowed, the most likely allowed class. The confidence is the mean
    probability of the chosen characters (0 for an empty reading)."""
    best = _best(logits, allowed)
    chars = []
    for index in best.tolist():
        if index >= len(vocab):  # <eos> (or another special token)
            break
        chars.append(vocab[index])
    if not chars:
        return "", 0.0
    positions = np.arange(len(chars))
    probabilities = _softmax(logits[: len(chars)])[positions, best[: len(chars)]]
    return "".join(chars), float(np.clip(probabilities, 0.0, 1.0).mean())


def scoresight_patch(tesseract, crop_bgr: np.ndarray, field_type: str):
    """The grayscale image ScoreSight's TextDetector would hand to Tesseract for a
    box covering the whole crop, with the default box settings of the field
    type, or None if ScoreSight would not read it (a blank patch). tesseract is
    ScoreSight's src/tesseract.py module. Mirrors TextDetector._detect_box and
    _recognize up to the Tesseract call (the multi-frame and dot-counter
    options are off for evaluation)."""
    settings = box_settings(field_type)
    gray = cv2.cvtColor(crop_bgr, cv2.COLOR_BGR2GRAY)
    height, width = gray.shape[:2]
    patch = tesseract.preprocess_patch(
        settings,
        (0, 0, width, height),
        gray,
        lambda: tesseract.global_binarization(gray),
    )
    if settings.get("invert_patch"):
        patch = 255 - patch
    if not tesseract.has_foreground(patch):
        return None
    if settings.get("autocrop"):
        patch, _ = tesseract.autocrop(patch)
    if patch.shape[0] == 0 or patch.shape[1] == 0:
        return None
    if settings.get("rescale_patch"):
        scale = 35 / patch.shape[0]
        patch = cv2.resize(
            patch, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA
        )
        if patch.shape[0] == 0 or patch.shape[1] == 0:
            return None
    return patch


def onnx_threads() -> int:
    """$OCR_EVAL_ONNX_THREADS, the intra-op threads (0: onnxruntime's default)."""
    value = os.environ.get(THREADS_ENV, "").strip()
    if not value:
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        raise EngineUnavailable(
            f"{THREADS_ENV} must be a number of threads, not {value!r}"
        ) from None


def _version(package: str) -> str | None:
    try:
        return importlib.metadata.version(package)
    except importlib.metadata.PackageNotFoundError:
        return None


class OnnxTR(Engine):
    name = "onnxtr"
    variants = tuple(f"{model}{suffix}" for model in MODELS for suffix in SUFFIXES)
    default_variants = tuple(
        f"{model}{suffix}"
        for model, spec in MODELS.items()
        if not spec.int8
        for suffix in SUFFIXES
    )
    description = "docTR word recognizers (OnnxTR's ONNX exports)"
    license = "Apache-2.0 (docTR models, OnnxTR)"
    runtime = "ONNX Runtime, CPU"
    imports = ("onnxtr", "onnxruntime")
    # a frame's boxes are read together; ScoreSight setups have up to ~16 boxes
    batch_size = 16

    def __init__(self, variant: str | None = None):
        super().__init__(variant)
        model_name, suffix = split_variant(self.variant)
        self.model = MODELS[model_name]
        self.binarize, self.restrict = SUFFIXES[suffix]
        self.threads = 0
        self._predictor = None
        self._tesseract = None
        self._split = None
        self._allowed: dict[str, np.ndarray] = {}

    def load(self) -> None:
        self.threads = onnx_threads()
        try:
            import onnxruntime as ort
            from onnxtr.models import EngineConfig, recognition_predictor
            from onnxtr.models.recognition.predictor._utils import (
                remap_preds,
                split_crops,
            )
        except ImportError as e:
            raise EngineUnavailable(
                f"can't import OnnxTR: {e} (pip install {' '.join(REQUIREMENTS)})"
            ) from e
        if self.binarize:
            isolate_app_state()
            try:
                import tesseract  # ScoreSight's src/tesseract.py
            except ImportError as e:
                raise EngineUnavailable(
                    f"ScoreSight's preprocessing needs src/tesseract.py: {e}"
                ) from e
            self._tesseract = tesseract

        options = ort.SessionOptions()
        options.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
        options.intra_op_num_threads = self.threads
        config = EngineConfig(
            providers=["CPUExecutionProvider"], session_options=options
        )
        try:
            predictor = recognition_predictor(
                self.model.arch,
                batch_size=self.batch_size,
                load_in_8_bit=self.model.int8,
                engine_cfg=config,
            )
        except OSError as e:  # no network for the first download, unreadable file
            raise EngineUnavailable(
                f"can't download or open the {self.model.arch} model: {e}"
            ) from e
        self.use_predictor(predictor, split_crops, remap_preds)

    def use_predictor(self, predictor, split_crops=None, remap_preds=None) -> None:
        """Read with an OnnxTR RecognitionPredictor (or a stand-in with its
        pre_processor, model, model.vocab and split_wide_crops attributes);
        split_crops and remap_preds are OnnxTR's wide-crop helpers, needed when
        predictor.split_wide_crops is set."""
        self._predictor = predictor
        self._split = (split_crops, remap_preds)
        vocab = predictor.model.vocab
        self._allowed = {
            field_type: allowed_classes(vocab, whitelist(field_type))
            for field_type in FIELD_TYPES
        }

    def _image(self, crop: np.ndarray, field_type: str) -> np.ndarray | None:
        if not self.binarize:
            return cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        patch = scoresight_patch(self._tesseract, crop, field_type)
        return None if patch is None else cv2.cvtColor(patch, cv2.COLOR_GRAY2RGB)

    def recognize(self, crops, field_types):
        results: list[Recognition | None] = [None] * len(crops)
        indices, images = [], []
        for i, (crop, field_type) in enumerate(zip(crops, field_types)):
            image = self._image(crop, field_type)
            if image is None:
                results[i] = Recognition("", None, {"state": "Empty"})
            else:
                indices.append(i)
                images.append(image)
        if images:
            readings = self._read(images, [field_types[i] for i in indices])
            for i, reading in zip(indices, readings):
                results[i] = reading
        return results

    def _read(self, images: list[np.ndarray], field_types: list[str]):
        """What OnnxTR's RecognitionPredictor.__call__ does (split very wide
        crops, resize and normalize, run the model, merge the pieces of split
        crops), keeping the logits for whitelist-restricted decoding."""
        predictor = self._predictor
        split_crops, remap_preds = self._split
        pieces, crop_map, remapped = images, None, False
        if predictor.split_wide_crops:
            pieces, crop_map, remapped = split_crops(
                images,
                predictor.critical_ar,
                predictor.target_ar,
                predictor.overlap_ratio,
                True,
            )
        piece_types = list(field_types)
        if remapped:
            piece_types = [""] * len(pieces)
            for owner, item in enumerate(crop_map):
                start, end = (item, item + 1) if isinstance(item, int) else item[:2]
                piece_types[start:end] = [field_types[owner]] * (end - start)

        decode = decode_ctc if self.model.decoder == "ctc" else decode_attention
        vocab = predictor.model.vocab
        free, restricted = [], []
        for batch in predictor.pre_processor(pieces):
            out = predictor.model(batch, return_model_output=self.restrict)
            free.extend(out["preds"])
            if self.restrict:
                for logits in out["out_map"]:
                    allowed = self._allowed[piece_types[len(restricted)]]
                    restricted.append(decode(logits, vocab, allowed))
        if remapped:
            free = remap_preds(free, crop_map, predictor.overlap_ratio)
            if self.restrict:
                restricted = remap_preds(restricted, crop_map, predictor.overlap_ratio)

        readings = []
        for i, (text, confidence) in enumerate(free):
            info = None
            if self.restrict:
                unrestricted = text
                text, confidence = restricted[i]
                if text != unrestricted:
                    info = {"unrestricted": unrestricted}
            readings.append(Recognition(text, round(float(confidence), 4), info))
        return readings

    def close(self) -> None:
        self._predictor = None
        self._tesseract = None

    def info(self) -> dict:
        info = super().info()
        info["description"] = self.model.description
        info["size"] = f"{self.model.params} parameters" if self.model.params else ""
        info["model"] = self.model.arch
        info["int8"] = self.model.int8
        info["decoder"] = self.model.decoder
        info["preprocessing"] = (
            "ScoreSight's (binarized patch)" if self.binarize else "raw RGB crop"
        )
        info["whitelist_decoding"] = self.restrict
        info["threads"] = self.threads or "onnxruntime default"
        versions = {p: _version(p) for p in ("onnxtr", "onnxruntime")}
        info["version"] = ", ".join(f"{p} {v}" for p, v in versions.items() if v)
        if self._predictor is not None:
            model_path = Path(str(self._predictor.model.model_path))
            if model_path.is_file():
                megabytes = model_path.stat().st_size / 1e6
                file_size = f"{megabytes:.1f} MB ({model_path.name})"
                info["size"] = ", ".join(filter(None, [info["size"], file_size]))
            info["vocab_size"] = len(self._predictor.model.vocab)
        return info
