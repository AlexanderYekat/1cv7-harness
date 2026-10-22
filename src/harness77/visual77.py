"""Visual form tests: an approved baseline image against this run's capture (task 010).

The native backend opens the form in the run's own 1C session, shows it on the
run's private desktop and captures the declared *states* (``open``: right after
opening; ``clicked``: after the button click) as PNG files with the capture
environment. This module is portable: it compares a capture with the approved
baseline of its check, pixel by pixel outside the declared masks, and writes
the baseline, the capture, an image of the differences and a machine result
into the run directory.

A baseline exists only after an explicit ``harness77 visual approve``; a run
never writes it, whatever the outcome. A missing capture, an unstable capture,
a missing or altered baseline, or a capture environment that differs from the
baseline's blocks the comparison instead of passing or failing it.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
import shutil
import struct
import zlib

from .report77 import BLOCKED, FAILED, PASSED, SKIPPED, Stage, atomic_json, file_evidence, sha256_file

PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
# Colour types with 8-bit samples this reader accepts, by channels per pixel.
CHANNELS = {0: 1, 2: 3, 6: 4}
STATES = ("open", "clicked")
WINDOWS = ("form", "dialog")
CHECK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
# Every key must be recorded, and equal, for a capture to be compared with a baseline.
ENVIRONMENT_KEYS = ("platform_version", "configuration", "windows_build", "system_dpi", "window_dpi",
                    "theme", "font", "locale", "capture")
BASELINE_SCHEMA = "harness77-visual-baseline"
STAGE_SCOPE = "pixel comparison of this run's form captures with approved baselines"


class VisualError(ValueError):
    """An unreadable image or an unusable comparison input."""


@dataclass(frozen=True)
class Image:
    width: int
    height: int
    rgb: bytes  # rows top-down, 3 bytes per pixel

    def __post_init__(self):
        if self.width <= 0 or self.height <= 0 or len(self.rgb) != self.width * self.height * 3:
            raise VisualError(f"image data does not match {self.width}x{self.height} RGB")

    def pixel(self, x, y):
        offset = (y * self.width + x) * 3
        return tuple(self.rgb[offset:offset + 3])

    def colours(self, limit=256):
        """Distinct colours, counted up to ``limit`` (a uniform image has one)."""
        seen = set()
        for offset in range(0, len(self.rgb), 3):
            seen.add(self.rgb[offset:offset + 3])
            if len(seen) >= limit:
                break
        return len(seen)


def _chunk(tag, data):
    return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)


def encode_png(image):
    """PNG bytes of an RGB image: 8-bit truecolour, filter 0, no ancillary chunks.

    The bytes depend on the pixels only, so equal images give equal hashes.
    """
    stride = image.width * 3
    raw = b"".join(b"\0" + image.rgb[y * stride:(y + 1) * stride] for y in range(image.height))
    header = struct.pack(">IIBBBBB", image.width, image.height, 8, 2, 0, 0, 0)
    return PNG_SIGNATURE + _chunk(b"IHDR", header) + _chunk(b"IDAT", zlib.compress(raw, 9)) + _chunk(b"IEND", b"")


def write_png(path, image):
    Path(path).write_bytes(encode_png(image))


def _paeth(left, up, corner):
    estimate = left + up - corner
    a, b, c = abs(estimate - left), abs(estimate - up), abs(estimate - corner)
    return left if a <= b and a <= c else up if b <= c else corner


def _unfilter(kind, line, previous, bpp):
    if kind == 0:
        return line
    out = bytearray(line)
    for i in range(len(out)):
        left = out[i - bpp] if i >= bpp else 0
        up = previous[i]
        corner = previous[i - bpp] if i >= bpp else 0
        if kind == 1:
            out[i] = (out[i] + left) & 0xFF
        elif kind == 2:
            out[i] = (out[i] + up) & 0xFF
        elif kind == 3:
            out[i] = (out[i] + ((left + up) >> 1)) & 0xFF
        elif kind == 4:
            out[i] = (out[i] + _paeth(left, up, corner)) & 0xFF
        else:
            raise VisualError(f"unknown PNG filter {kind}")
    return bytes(out)


def decode_png(data):
    """RGB image of a non-interlaced 8-bit grey, RGB or RGBA PNG; alpha is dropped.

    Anything else is refused explicitly: the baselines are this tool's own captures.
    """
    if not data.startswith(PNG_SIGNATURE):
        raise VisualError("not a PNG file")
    position, header, idat = len(PNG_SIGNATURE), None, []
    while position + 12 <= len(data):
        length, tag = struct.unpack(">I4s", data[position:position + 8])
        body = data[position + 8:position + 8 + length]
        if len(body) != length or position + 12 + length > len(data):
            raise VisualError("truncated PNG chunk")
        crc = struct.unpack(">I", data[position + 8 + length:position + 12 + length])[0]
        if zlib.crc32(tag + body) & 0xFFFFFFFF != crc:
            raise VisualError(f"PNG chunk {tag.decode('latin-1')} checksum mismatch")
        position += 12 + length
        if tag == b"IHDR":
            header = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat.append(body)
        elif tag == b"IEND":
            break
    else:
        raise VisualError("PNG has no IEND chunk")
    if header is None or not idat:
        raise VisualError("PNG has no IHDR or IDAT")
    width, height, depth, colour, _, _, interlace = header
    if depth != 8 or colour not in CHANNELS or interlace:
        raise VisualError(f"unsupported PNG: depth {depth}, colour type {colour}, interlace {interlace}")
    bpp = CHANNELS[colour]
    stride = width * bpp
    try:
        raw = zlib.decompress(b"".join(idat))
    except zlib.error as error:
        raise VisualError(f"PNG data is not readable: {error}") from None
    if len(raw) != height * (stride + 1):
        raise VisualError("PNG data length does not match its size")
    rows, previous = [], bytes(stride)
    for y in range(height):
        start = y * (stride + 1)
        previous = _unfilter(raw[start], raw[start + 1:start + 1 + stride], previous, bpp)
        rows.append(previous)
    pixels = b"".join(rows)
    if colour == 2:
        rgb = pixels
    elif colour == 6:
        rgb = bytes(b for i in range(0, len(pixels), 4) for b in pixels[i:i + 3])
    else:
        rgb = bytes(b for value in pixels for b in (value, value, value))
    return Image(width, height, rgb)


def read_png(path):
    return decode_png(Path(path).read_bytes())


# --- the [visual] section of the project profile ------------------------------

@dataclass(frozen=True)
class VisualCheck:
    name: str
    state: str
    window: str
    channel_tolerance: int
    max_diff_pixels: int
    mask_caret: bool
    masks: tuple

    def public(self):
        return {"name": self.name, "state": self.state, "window": self.window,
                "channel_tolerance": self.channel_tolerance, "max_diff_pixels": self.max_diff_pixels,
                "mask_caret": self.mask_caret, "masks": [dict(m) for m in self.masks]}


@dataclass(frozen=True)
class VisualConfig:
    baselines: Path
    checks: tuple

    def captures(self):
        """The states and windows the backend must capture, without repeats."""
        return [dict(state=s, window=w) for s, w in dict.fromkeys((c.state, c.window) for c in self.checks)]

    def public(self):
        return {"baselines": self.baselines.name, "checks": [c.public() for c in self.checks]}


def _integer(value, where, low, high=None):
    if isinstance(value, bool) or not isinstance(value, int) or value < low or (high is not None and value > high):
        bound = f"{low}…{high}" if high is not None else f"не меньше {low}"
        raise VisualError(f"{where}: нужно целое число {bound}, получено {value!r}")
    return value


def parse_mask(item, where):
    if not isinstance(item, dict):
        raise VisualError(f"{where}: маска — таблица x, y, width, height, reason")
    unknown = set(item) - {"x", "y", "width", "height", "reason"}
    if unknown:
        raise VisualError(f"{where}: неизвестные ключи маски: {', '.join(sorted(unknown))}")
    mask = {key: _integer(item.get(key), f"{where}.{key}", 0) for key in ("x", "y")}
    mask.update({key: _integer(item.get(key), f"{where}.{key}", 1) for key in ("width", "height")})
    reason = item.get("reason")
    if not isinstance(reason, str) or not reason.strip():
        raise VisualError(f"{where}: у маски нужна причина (reason)")
    mask["reason"] = reason
    return mask


def parse_config(table, base_dir, where="visual"):
    """``[visual]``: the baselines directory and at least one ``[[visual.checks]]``."""
    if not isinstance(table, dict):
        raise VisualError(f"{where}: ожидается таблица")
    unknown = set(table) - {"baselines", "checks"}
    if unknown:
        raise VisualError(f"{where}: неизвестные ключи: {', '.join(sorted(unknown))}")
    baselines = table.get("baselines")
    if not isinstance(baselines, str) or not baselines:
        raise VisualError(f"{where}.baselines: нужен путь к каталогу эталонов")
    path = Path(baselines)
    checks, names = [], set()
    items = table.get("checks")
    if not isinstance(items, list) or not items:
        raise VisualError(f"{where}: нужна хотя бы одна проверка [[visual.checks]]")
    allowed = {"name", "state", "window", "channel_tolerance", "max_diff_pixels", "mask_caret", "masks"}
    for index, item in enumerate(items):
        place = f"{where}.checks[{index}]"
        if not isinstance(item, dict):
            raise VisualError(f"{place}: ожидается таблица")
        if set(item) - allowed:
            raise VisualError(f"{place}: неизвестные ключи: {', '.join(sorted(set(item) - allowed))}")
        name = item.get("name")
        if not isinstance(name, str) or not CHECK_NAME.fullmatch(name):
            raise VisualError(f"{place}.name: латиница, цифры, '.', '_', '-', до 64 знаков")
        if name in names:
            raise VisualError(f"{place}.name: повтор имени {name}")
        names.add(name)
        state, window = item.get("state"), item.get("window", "form")
        if state not in STATES:
            raise VisualError(f"{place}.state: одно из {STATES}")
        if window not in WINDOWS:
            raise VisualError(f"{place}.window: одно из {WINDOWS}")
        mask_caret = item.get("mask_caret", True)
        if not isinstance(mask_caret, bool):
            raise VisualError(f"{place}.mask_caret: true или false")
        masks = item.get("masks", [])
        if not isinstance(masks, list):
            raise VisualError(f"{place}.masks: ожидается список")
        checks.append(VisualCheck(
            name=name, state=state, window=window,
            channel_tolerance=_integer(item.get("channel_tolerance", 0), f"{place}.channel_tolerance", 0, 255),
            max_diff_pixels=_integer(item.get("max_diff_pixels", 0), f"{place}.max_diff_pixels", 0),
            mask_caret=mask_caret,
            masks=tuple(parse_mask(m, f"{place}.masks[{i}]") for i, m in enumerate(masks))))
    return VisualConfig(baselines=path if path.is_absolute() else Path(base_dir) / path, checks=tuple(checks))


# --- comparison ----------------------------------------------------------------

def _mask_grid(width, height, masks):
    grid = bytearray(width * height)
    for mask in masks:
        left, top = max(0, mask["x"]), max(0, mask["y"])
        right, bottom = min(width, mask["x"] + mask["width"]), min(height, mask["y"] + mask["height"])
        for y in range(top, bottom):
            grid[y * width + left:y * width + right] = b"\1" * max(0, right - left)
    return grid


def compare(baseline, actual, *, masks=(), channel_tolerance=0, max_diff_pixels=0):
    """Compare two images outside ``masks``; returns ``(result, diff_image)``.

    A pixel differs when any channel differs by more than ``channel_tolerance``
    or when it lies in only one of the images (sizes differ). The check passes
    when the sizes are equal and at most ``max_diff_pixels`` pixels differ. The
    diff image is the capture in light grey, differing pixels red, masks blue.
    """
    width, height = max(baseline.width, actual.width), max(baseline.height, actual.height)
    grid = _mask_grid(width, height, masks)
    diff = bytearray(width * height * 3)
    differing = masked = worst = 0
    box = [width, height, -1, -1]
    for y in range(height):
        in_base, in_actual = y < baseline.height, y < actual.height
        row_b = baseline.rgb[y * baseline.width * 3:(y + 1) * baseline.width * 3] if in_base else b""
        row_a = actual.rgb[y * actual.width * 3:(y + 1) * actual.width * 3] if in_actual else b""
        source, source_width = (row_a, actual.width) if in_actual else (row_b, baseline.width)
        same_row = in_base and in_actual and baseline.width == actual.width and row_b == row_a
        for x in range(width):
            index = y * width + x
            if x < source_width:
                r, g, b = source[x * 3:x * 3 + 3]
                light = 150 + (r * 30 + g * 59 + b * 11) * 105 // 25500
            else:
                light = 255
            if grid[index]:
                masked += 1
                pixel = (light * 3 // 5, light * 3 // 5, 255)
            elif same_row:
                pixel = (light, light, light)
            else:
                delta = None
                if in_base and in_actual and x < baseline.width and x < actual.width:
                    delta = max(abs(p - q) for p, q in zip(row_b[x * 3:x * 3 + 3], row_a[x * 3:x * 3 + 3]))
                    worst = max(worst, delta)
                if delta is None or delta > channel_tolerance:
                    differing += 1
                    box = [min(box[0], x), min(box[1], y), max(box[2], x), max(box[3], y)]
                    pixel = (255, 0, 0)
                else:
                    pixel = (light, light, light)
            diff[index * 3:index * 3 + 3] = bytes(pixel)
    same_size = (baseline.width, baseline.height) == (actual.width, actual.height)
    passed = same_size and differing <= max_diff_pixels
    result = {"status": PASSED if passed else FAILED,
              "size": {"baseline": [baseline.width, baseline.height], "actual": [actual.width, actual.height],
                       "equal": same_size},
              "pixels": width * height, "masked_pixels": masked, "diff_pixels": differing,
              "max_channel_delta": worst,
              "diff_box": None if differing == 0 else
              {"x": box[0], "y": box[1], "width": box[2] - box[0] + 1, "height": box[3] - box[1] + 1},
              "tolerance": {"channel": channel_tolerance, "max_diff_pixels": max_diff_pixels}}
    if not passed:
        result["reason"] = ("image size differs" if not same_size
                            else f"{differing} pixels differ (allowed {max_diff_pixels})")
    return result, Image(width, height, bytes(diff))


def environment_issues(baseline, actual):
    """Why a capture made in ``actual`` cannot be compared with a baseline made in ``baseline``."""
    issues = []
    for key in ENVIRONMENT_KEYS:
        have, want = (actual or {}).get(key), (baseline or {}).get(key)
        if have is None or want is None:
            issues.append(f"{key}: not recorded" + (" for the baseline" if want is None else " for the capture"))
        elif have != want:
            issues.append(f"{key}: baseline {json.dumps(want, ensure_ascii=False, sort_keys=True)}, "
                          f"capture {json.dumps(have, ensure_ascii=False, sort_keys=True)}")
    return issues


# --- baselines -----------------------------------------------------------------

def baseline_paths(config, check):
    return config.baselines / (check.name + ".png"), config.baselines / (check.name + ".json")


def load_baseline(config, check):
    """``(record, image)`` of the check's approved baseline; raises VisualError when unusable."""
    image_path, record_path = baseline_paths(config, check)
    if not record_path.exists() and not image_path.exists():
        raise VisualError(f"no approved baseline for '{check.name}' in {config.baselines.name}; "
                          "approve one with: harness77 visual approve")
    try:
        record = json.loads(record_path.read_text(encoding="utf-8"))
        data = image_path.read_bytes()
    except (OSError, ValueError) as error:
        raise VisualError(f"baseline '{check.name}' is unreadable: {type(error).__name__}: {error}") from None
    if not isinstance(record, dict) or record.get("schema") != BASELINE_SCHEMA or record.get("schema_version") != 1:
        raise VisualError(f"baseline '{check.name}': not a {BASELINE_SCHEMA} 1 record")
    if (record.get("check"), record.get("state"), record.get("window")) != (check.name, check.state, check.window):
        raise VisualError(f"baseline '{check.name}' was approved for another state or window: "
                          f"{record.get('state')}/{record.get('window')}")
    if hashlib.sha256(data).hexdigest() != (record.get("image") or {}).get("sha256"):
        raise VisualError(f"baseline '{check.name}': the image does not match its record (SHA-256)")
    return record, decode_png(data)


def _capture_for(captures, check):
    return next((c for c in captures or [] if c.get("state") == check.state and c.get("window") == check.window),
                None)


def _capture_issue(capture, run_dir):
    """Why a reported capture cannot be compared; None when it can."""
    if capture is None:
        return "no capture of this state and window in the platform result"
    if capture.get("error"):
        return "capture failed: " + str(capture["error"])
    if capture.get("stable") is not True:
        return f"capture is not stable after {capture.get('attempts')} attempts"
    file = capture.get("file") or {}
    if file.get("exists") is not True or file.get("complete") is not True or not file.get("path"):
        return "capture file missing or incomplete"
    if not (Path(run_dir) / file["path"]).is_file():
        return "capture file missing"
    return None


def caret_masks(capture, record, check):
    """The system caret blinks: its rectangle, in the capture and in the baseline, is masked."""
    if not check.mask_caret:
        return []
    masks = []
    for owner, source in (("capture", capture), ("baseline", record)):
        caret = (source or {}).get("caret")
        if caret:
            masks.append({key: caret[key] for key in ("x", "y", "width", "height")}
                         | {"reason": f"system caret ({owner})"})
    return masks


def check_capture(config, check, capture, run_dir, out_dir):
    """Compare one capture with its baseline; writes the evidence into ``out_dir``."""
    row = {"name": check.name, "state": check.state, "window": check.window, "status": BLOCKED, "reason": None}
    issue = _capture_issue(capture, run_dir)
    if issue:
        row["reason"] = issue
        return row
    actual_path = Path(run_dir) / capture["file"]["path"]
    try:
        record, baseline = load_baseline(config, check)
    except VisualError as error:
        row["reason"] = str(error)
        return row
    issues = environment_issues(record.get("environment"), capture.get("environment"))
    if issues:
        row.update(reason="capture environment differs from the baseline's", environment_issues=issues)
        return row
    try:
        actual = read_png(actual_path)
    except (OSError, VisualError) as error:
        row["reason"] = f"capture is unreadable: {error}"
        return row
    masks = list(check.masks) + caret_masks(capture, record, check)
    result, diff = compare(baseline, actual, masks=masks, channel_tolerance=check.channel_tolerance,
                           max_diff_pixels=check.max_diff_pixels)
    out_dir.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(baseline_paths(config, check)[0], out_dir / "baseline.png")
    shutil.copyfile(actual_path, out_dir / "actual.png")
    write_png(out_dir / "diff.png", diff)
    root = Path(run_dir)
    row.update(result, masks=masks,
               baseline={"sha256": record["image"]["sha256"], "approved": record.get("approved")},
               capture={"path": capture["file"]["path"], "sha256": capture["file"].get("sha256")})
    atomic_json(out_dir / "result.json", row)
    row["files"] = {role: file_evidence(out_dir / name, root=root, complete=True)
                    for role, name in (("baseline", "baseline.png"), ("actual", "actual.png"),
                                       ("diff", "diff.png"), ("result", "result.json"))}
    return row


def visual_stage(config, platform_result, run_dir, platform_passed):
    """The ``visual`` stage of ``run``: every declared check against its approved baseline."""
    stage = Stage("visual", required=True, scope=STAGE_SCOPE)
    if not platform_passed:
        return stage.finish(SKIPPED, reason="platform check did not pass; captures not compared")
    captures = platform_result.get("captures") or []
    rows = []
    for check in config.checks:
        try:
            rows.append(check_capture(config, check, _capture_for(captures, check), run_dir,
                                      Path(run_dir) / "visual" / check.name))
        except OSError as error:  # writing the evidence failed: nothing was judged
            rows.append({"name": check.name, "state": check.state, "window": check.window, "status": BLOCKED,
                         "reason": f"visual evidence not written: {type(error).__name__}: {error}"})
    statuses = {row["status"] for row in rows}
    status = BLOCKED if BLOCKED in statuses else FAILED if FAILED in statuses else PASSED
    first = next((r for r in rows if r["status"] == status), None) if status != PASSED else None
    reason = f"{first['name']}: {first['reason']}" if first else None
    return stage.finish(status, reason=reason, checks=rows, baselines=config.baselines.name)


def approve(config, run_dir, *, checks=None, approved_by, replace=False, now=None):
    """Make this run's captures the baselines of the named checks (all by default).

    Refused, with nothing written, when the run did not pass its platform check,
    a capture is missing, unstable, changed or without its environment, or a
    baseline exists and ``replace`` is false.
    """
    run_dir = Path(run_dir)
    try:
        report = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise VisualError(f"run report is unreadable: {type(error).__name__}: {error}") from None
    stages = {s.get("stage"): s for s in report.get("stages", [])}
    platform = stages.get("platform_check") or {}
    if platform.get("status") != PASSED:
        raise VisualError("the run did not pass its platform check; nothing to approve")
    names = list(checks) if checks else [c.name for c in config.checks]
    unknown = [n for n in names if n not in {c.name for c in config.checks}]
    if unknown:
        raise VisualError("no such visual check in the project: " + ", ".join(unknown))
    plan = []
    for check in (c for c in config.checks if c.name in names):
        capture = _capture_for(platform.get("captures"), check)
        issue = _capture_issue(capture, run_dir)
        if issue:
            raise VisualError(f"{check.name}: {issue}")
        missing = [k for k in ENVIRONMENT_KEYS if (capture.get("environment") or {}).get(k) is None]
        if missing:
            raise VisualError(f"{check.name}: capture environment not recorded: {', '.join(missing)}")
        source = run_dir / capture["file"]["path"]
        if sha256_file(source) != capture["file"].get("sha256"):
            raise VisualError(f"{check.name}: the capture file changed after the run")
        image = read_png(source)
        image_path, record_path = baseline_paths(config, check)
        previous = None
        if image_path.exists() or record_path.exists():
            if not replace:
                raise VisualError(f"{check.name}: a baseline exists; pass --replace to replace it explicitly")
            previous = sha256_file(image_path) if image_path.exists() else None
        plan.append((check, capture, source, image, previous))
    config.baselines.mkdir(parents=True, exist_ok=True)
    stamp = (now or dt.datetime.now().astimezone()).isoformat()
    form = (stages.get("build") or {}).get("form") or {}
    approved = []
    for check, capture, source, image, previous in plan:
        image_path, record_path = baseline_paths(config, check)
        temporary = image_path.with_name(image_path.name + ".tmp")
        shutil.copyfile(source, temporary)
        temporary.replace(image_path)
        record = {"schema": BASELINE_SCHEMA, "schema_version": 1, "check": check.name, "state": check.state,
                  "window": check.window,
                  "image": {"sha256": sha256_file(image_path), "width": image.width, "height": image.height},
                  "environment": capture["environment"], "caret": capture.get("caret"),
                  "approved": {"by": approved_by, "at": stamp, "run_id": report.get("run_id"),
                               "ert_sha256": (report.get("artifact") or {}).get("sha256"),
                               "form_sha256": form.get("sha256"),
                               # A form of the configuration (task 022): the built 1Cv7.MD of the run.
                               **({"configuration_sha256": report["configuration"].get("sha256")}
                                  if report.get("configuration") else {}),
                               "tests": (stages.get("tests") or {}).get("status")},
                  "masks_at_approval": [dict(m) for m in check.masks], "replaces_sha256": previous}
        atomic_json(record_path, record)
        approved.append({"check": check.name, "sha256": record["image"]["sha256"], "replaced": previous})
    return approved


# --- CLI -----------------------------------------------------------------------

def _rect(text):
    try:
        x, y, width, height = (int(part) for part in text.split(","))
        return parse_mask({"x": x, "y": y, "width": width, "height": height, "reason": "command line"}, "--mask")
    except (ValueError, VisualError) as error:
        raise ValueError(f"--mask x,y,width,height: {error}") from None


def main(argv=None):
    import argparse
    import sys
    parser = argparse.ArgumentParser(prog="harness77 visual", allow_abbrev=False,
                                     description="Визуальные тесты форм: сравнение снимков и утверждение эталонов")
    actions = parser.add_subparsers(dest="action", required=True)
    one = actions.add_parser("compare", help="Сравнить два PNG и записать изображение различий")
    one.add_argument("baseline", type=Path)
    one.add_argument("actual", type=Path)
    one.add_argument("--output", type=Path, required=True, help="Новый каталог для diff.png и result.json")
    one.add_argument("--mask", action="append", default=[], type=_rect, help="x,y,width,height; можно повторять")
    one.add_argument("--channel-tolerance", type=int, default=0)
    one.add_argument("--max-diff-pixels", type=int, default=0)
    take = actions.add_parser("approve", help="Утвердить снимки запуска как эталоны проверок проекта")
    take.add_argument("--project", type=Path, required=True)
    take.add_argument("--run", type=Path, required=True, help="Каталог запуска harness77 run")
    take.add_argument("--check", action="append", default=[], help="Имя проверки; по умолчанию все")
    take.add_argument("--by", required=True, help="Кто утверждает эталон")
    take.add_argument("--replace", action="store_true", help="Явно заменить существующий эталон")
    args = parser.parse_args(argv)
    try:
        if args.action == "compare":
            tolerance = _integer(args.channel_tolerance, "--channel-tolerance", 0, 255)
            allowed = _integer(args.max_diff_pixels, "--max-diff-pixels", 0)
            baseline, actual = read_png(args.baseline), read_png(args.actual)
            result, diff = compare(baseline, actual, masks=args.mask, channel_tolerance=tolerance,
                                   max_diff_pixels=allowed)
            args.output.mkdir(parents=True, exist_ok=False)
            write_png(args.output / "diff.png", diff)
            result.update(baseline_sha256=sha256_file(args.baseline), actual_sha256=sha256_file(args.actual),
                          masks=args.mask)
            atomic_json(args.output / "result.json", result)
            print(json.dumps(result, ensure_ascii=False, indent=2))
            return 0 if result["status"] == PASSED else 1
        from .config77 import load_project
        project = load_project(args.project)
        if project.visual is None:
            raise VisualError("the project has no [visual] section")
        approved = approve(project.visual, args.run, checks=args.check, approved_by=args.by, replace=args.replace)
        print(json.dumps({"status": "approved", "baselines": approved}, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError) as error:
        print(json.dumps({"status": BLOCKED, "reason": f"{type(error).__name__}: {error}"},
                         ensure_ascii=False, indent=2), file=sys.stderr)
        return 2
