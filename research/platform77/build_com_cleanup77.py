"""Build the optional x86 diagnostic helper; does not register or load it."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(allow_abbrev=False)
    parser.add_argument("--clang", required=True, type=Path)
    parser.add_argument("--link", required=True, type=Path)
    parser.add_argument("--sdk-lib", required=True, type=Path, help="Windows SDK um/x86 directory")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--identity", action="store_true", help="build the separate client proxy inspector")
    args = parser.parse_args()
    source = Path(__file__).resolve().parent
    clang, linker, sdk = [p.resolve(strict=True) for p in (args.clang, args.link, args.sdk_lib)]
    libraries = [sdk / name for name in ("ole32.lib", "oleaut32.lib", "kernel32.lib")]
    for library in libraries:
        library.resolve(strict=True)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    stem = "proxy_identity77" if args.identity else "com_cleanup77"
    obj, dll = out / (stem + ".obj"), out / (stem + ".dll")
    commands = [
        [str(clang), "--target=i686-pc-windows-msvc", "-O2", "-Wall", "-Wextra", "-Werror",
         "-fno-builtin", "-c", str(source / (stem + ".c")), "-o", str(obj)],
        [str(linker), "/dll", "/noentry", "/machine:x86", "/nodefaultlib",
         "/def:" + str(source / (stem + ".def")), "/out:" + str(dll), str(obj),
         *map(str, libraries)],
    ]
    for command in commands:
        subprocess.run(command, check=True, timeout=60)
    data = dll.read_bytes()
    pe = int.from_bytes(data[0x3c:0x40], "little")
    if data[pe:pe + 6] != b"PE\0\0\x4c\x01":
        raise RuntimeError("expected an x86 PE DLL")
    files = [source / (stem + ".c"), source / (stem + ".def"), dll]
    manifest = {"commands": commands, "sha256": {
        str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}}
    (out / "build.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(dll)


if __name__ == "__main__":
    main()
