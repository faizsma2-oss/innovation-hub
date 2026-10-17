"""Build the Copilot agent package: copilot/appPackage/openapi.json (only the Copilot endpoints,
pointing at the Hub's address) and copilot/innovation-hub-copilot.zip ready for the Microsoft 365
Agents Toolkit or the Teams admin centre.

    python scripts/build_copilot_package.py [https://hub-address]
"""
import json
import struct
import sys
import zipfile
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.main import app  # noqa: E402

ROOT = Path(__file__).resolve().parents[1] / "copilot"
PACKAGE = ROOT / "appPackage"
HUB = sys.argv[1] if len(sys.argv) > 1 else "https://innovation-hub-demo.onrender.com"


def png(size: int, rgba: tuple) -> bytes:
    """A plain square icon (Teams needs a 192×192 colour icon and a 32×32 outline)."""
    row = b"\x00" + bytes(rgba) * size
    raw = zlib.compress(row * size)
    chunk = lambda kind, data: struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


def to_openapi_30(node):
    """anyOf [X, null] (3.1) becomes X with nullable: true (3.0)."""
    if isinstance(node, list):
        return [to_openapi_30(item) for item in node]
    if not isinstance(node, dict):
        return node
    options = node.get("anyOf")
    if options and any(o == {"type": "null"} for o in options):
        rest = [o for o in options if o != {"type": "null"}]
        merged = {k: v for k, v in node.items() if k != "anyOf"} | (rest[0] if len(rest) == 1 else {"anyOf": rest})
        return to_openapi_30(merged | {"nullable": True})
    return {key: to_openapi_30(value) for key, value in node.items()}


def main():
    spec = app.openapi()
    paths = {path: ops for path, ops in spec["paths"].items() if path.startswith("/api/copilot/")}
    for ops in paths.values():
        for op in ops.values():
            # The API key comes from Copilot's key vault (security scheme below), not from the model.
            op["parameters"] = [p for p in op.get("parameters", []) if p["in"] != "header"]
            op["security"] = [{"hubKey": []}]
    paths = to_openapi_30(paths)
    used = json.dumps(paths)
    schemas = {name: s for name, s in spec.get("components", {}).get("schemas", {}).items() if f"/{name}\"" in used}
    # Copilot API plugins read OpenAPI 3.0; FastAPI writes 3.1.
    openapi = {"openapi": "3.0.3", "info": {"title": "Innovation Hub for Copilot", "version": "1.0.0"},
               "servers": [{"url": HUB}], "paths": paths,
               "components": {"securitySchemes": {"hubKey": {"type": "http", "scheme": "bearer"}},
                              **({"schemas": to_openapi_30(schemas)} if schemas else {})}}
    (PACKAGE / "openapi.json").write_text(json.dumps(openapi, indent=2))
    (PACKAGE / "color.png").write_bytes(png(192, (10, 132, 255, 255)))
    (PACKAGE / "outline.png").write_bytes(png(32, (255, 255, 255, 255)))
    with zipfile.ZipFile(ROOT / "innovation-hub-copilot.zip", "w", zipfile.ZIP_DEFLATED) as package:
        for file in sorted(PACKAGE.iterdir()):
            package.write(file, file.name)
    print(f"Built {ROOT / 'innovation-hub-copilot.zip'} for {HUB}: {', '.join(sorted(paths))}")


if __name__ == "__main__":
    main()
