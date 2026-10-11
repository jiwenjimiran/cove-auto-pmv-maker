"""Isolate blocking Resolve scripting calls from the companion HTTP server."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

from engine import Clip
from resolve_adapter import render


class FileCancel:
    def __init__(self, path):
        self.path = Path(path)

    def is_set(self):
        return self.path.exists()


def run(spec):
    cancel = FileCancel(spec["cancelPath"])
    if cancel.is_set():
        raise InterruptedError("Resolve render cancelled")
    clips = []
    for row in spec["clips"]:
        row["face_track"] = tuple(tuple(point) for point in row.get("face_track") or ())
        clips.append(Clip(**row))

    def progress(percent, message):
        print(json.dumps({"progress": percent, "message": message}), flush=True)

    render(clips, spec["audioPath"], spec["outputPath"], spec["width"], spec["height"],
           spec["fps"], spec["options"], spec["projectFolder"], cancel,
           progress, require_validation=spec["requireValidation"])


if __name__ == "__main__":
    try:
        run(json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")))
    except InterruptedError:
        print("Resolve render cancelled", file=sys.stderr, flush=True)
        sys.exit(2)
    except Exception:
        traceback.print_exc()
        sys.exit(1)
