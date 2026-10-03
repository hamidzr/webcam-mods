#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.13"
# dependencies = ["setuptools==84.0.0", "wheel==0.48.0", "delocate==0.13.0"]
# ///
"""Build pinned MediaPipe from source for macOS ARM64."""

import argparse
import hashlib
import os
import platform
import shlex
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

COMMIT = "32d0e5b1317be070083c630240b274218ce9ed52"
VERSION = "1.0.1+git32d0e5b"
BAZEL_VERSION = "7.7.0"
BAZEL_SHA256 = "2533ddc8628a96d1da3c5e99f45442d30fec93ee724316fd9687c78e56a84049"
PATCHES = (
    "620ce401.patch",
    "1d6e3acd.patch",
    "opencv-linker.patch",
    "opencv-sdk.patch",
)
MIN_FREE = 3 * 1024**3
REPO = Path(__file__).resolve().parents[1]


def run(args: list[str], source: Path, env: dict[str, str]) -> None:
    print(shlex.join(args), flush=True)
    subprocess.run(args, cwd=source, env=env, check=True)


def capture(args: list[str], source: Path, env: dict[str, str]) -> bytes:
    return subprocess.check_output(args, cwd=source, env=env)


def verify_source(source: Path, env: dict[str, str]) -> None:
    """Accept only the exact pinned source plus our build patches."""
    head = capture(["git", "rev-parse", "HEAD"], source, env).decode().strip()
    if head != COMMIT:
        raise RuntimeError(f"Source HEAD differs from pinned commit: {head}")
    with tempfile.TemporaryDirectory(prefix="mediapipe-index-") as scratch:
        index_env = env | {"GIT_INDEX_FILE": str(Path(scratch) / "index")}
        run(["git", "read-tree", "HEAD"], source, index_env)
        for name in PATCHES:
            run(
                ["git", "apply", "--cached", str(REPO / "vendor/mediapipe" / name)],
                source,
                index_env,
            )
        changed = capture(["git", "diff", "--cached", "--name-only"], source, index_env)
        expected_paths = set(changed.decode().splitlines())
        original_setup = capture(["git", "show", "HEAD:setup.py"], source, env)
        cached_setup = (
            original_setup.decode()
            .replace("__version__ = 'dev'", f"__version__ = '{VERSION}'")
            .replace(
                "BazelExtension('//mediapipe/tasks/c:libmediapipe.so')",
                "BazelExtension('//mediapipe/tasks/c:libmediapipe.dylib')",
            )
            .encode()
        )
        original_rc = capture(["git", "show", "HEAD:.bazelrc"], source, env)
        cached_rc = (
            f"startup --output_user_root={source.parent / 'bazel-cache'}\n".encode()
            + original_rc
            + b"\nbuild --jobs=10\nbuild --local_resources=memory=16000\nbuild --macos_minimum_os=11.0\n"
        )
        dirty = capture(
            ["git", "status", "--porcelain", "--untracked-files=all"], source, env
        )
        for line in dirty.decode().splitlines():
            path = line[3:]
            if path.startswith(("build/", "mediapipe.egg-info/")):
                continue
            if path in {"setup.py", ".bazelrc"}:
                expected = cached_setup if path == "setup.py" else cached_rc
                if (source / path).read_bytes() != expected:
                    raise RuntimeError(f"Unrelated source checkout change: {path}")
                continue
            if path not in expected_paths and path != "MODULE.bazel.lock":
                raise RuntimeError(f"Unrelated source checkout change: {path}")
        for path in expected_paths:
            expected = capture(["git", "show", f":{path}"], source, index_env)
            if (source / path).read_bytes() != expected:
                raise RuntimeError(f"Source patch content differs: {path}")


def prepare_source(source: Path, env: dict[str, str]) -> None:
    if not source.exists():
        source.mkdir(parents=True)
        run(["git", "init"], source, env)
        run(
            [
                "git",
                "remote",
                "add",
                "origin",
                "https://github.com/google-ai-edge/mediapipe.git",
            ],
            source,
            env,
        )
        run(["git", "fetch", "--depth=1", "origin", COMMIT], source, env)
        run(["git", "checkout", "--detach", "FETCH_HEAD"], source, env)
        for name in PATCHES:
            run(["git", "apply", str(REPO / "vendor/mediapipe" / name)], source, env)
    rc = source / ".bazelrc"
    original_rc = capture(["git", "show", "HEAD:.bazelrc"], source, env)
    if rc.read_bytes() == original_rc:
        rc.write_bytes(
            f"startup --output_user_root={source.parent / 'bazel-cache'}\n".encode()
            + original_rc
            + b"\nbuild --jobs=10\nbuild --local_resources=memory=16000\nbuild --macos_minimum_os=11.0\n"
        )
    verify_source(source, env)


def prepare_bazel(cache: Path) -> Path:
    executable = cache / "bin" / "bazel"
    executable.parent.mkdir(parents=True, exist_ok=True)
    if not executable.exists():
        url = f"https://github.com/bazelbuild/bazel/releases/download/{BAZEL_VERSION}/bazel-{BAZEL_VERSION}-darwin-arm64"
        temporary = executable.with_suffix(".download")
        urllib.request.urlretrieve(url, temporary)
        with temporary.open("rb") as stream:
            checksum = hashlib.file_digest(stream, "sha256").hexdigest()
        if checksum != BAZEL_SHA256:
            temporary.unlink()
            raise RuntimeError("Downloaded Bazel checksum mismatch")
        temporary.replace(executable)
        executable.chmod(0o755)
    with executable.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != BAZEL_SHA256:
            raise RuntimeError("Cached Bazel checksum mismatch")
    return executable


def build_native(
    bazel: Path, cache: Path, source: Path, env: dict[str, str], *, gpu: bool = False
) -> None:
    startup = [str(bazel), f"--output_user_root={cache / 'bazel-cache'}"]
    command = startup + [
        "build",
        "-c",
        "opt",
        "--jobs=10",
        "--local_ram_resources=16000",
        f"--define=MEDIAPIPE_DISABLE_GPU={0 if gpu else 1}",
        "--define=OPENCV=source",
        "--copt=-DNDEBUG",
        "--copt=-DLITERT_DISABLE_NPU",
        "--cpu=darwin_arm64",
        "--macos_minimum_os=11.0",
        "//mediapipe/tasks/c:libmediapipe.dylib",
    ]
    if shutil.disk_usage(cache).free < MIN_FREE:
        raise RuntimeError("Build needs at least 3 GiB free disk space")
    print(shlex.join(command), flush=True)
    process = subprocess.Popen(command, cwd=source, env=env)
    try:
        while process.poll() is None:
            if shutil.disk_usage(cache).free < MIN_FREE:
                raise RuntimeError("Stopped build: less than 3 GiB free disk space")
            time.sleep(5)
        if process.returncode:
            raise subprocess.CalledProcessError(process.returncode, command)
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            subprocess.run(startup + ["shutdown"], cwd=source, env=env, check=False)


def package_wheel(
    bazel: Path,
    cache: Path,
    source: Path,
    output: Path,
    env: dict[str, str],
    *,
    gpu: bool = False,
) -> None:
    # setup.py invokes bazel by name; keep metadata generation on the same cache
    wrapper_dir = cache / "packaging-bin"
    wrapper_dir.mkdir(exist_ok=True)
    wrapper = wrapper_dir / "bazel"
    wrapper.write_text(
        "#!/bin/sh\nexec "
        + shlex.join([str(bazel), f"--output_user_root={cache / 'bazel-cache'}"])
        + ' "$@"\n'
    )
    wrapper.chmod(0o755)
    package_env = env | {
        "PATH": f"{wrapper_dir}:{env['PATH']}",
        "SKIP_LIBMEDIAPIPE_BUILD": "1",
        "MEDIAPIPE_DISABLE_GPU": "0" if gpu else "1",
        "DYLD_LIBRARY_PATH": str(source / "bazel-bin/third_party/opencv_cmake/lib"),
    }
    setup = source / "setup.py"
    original = setup.read_bytes()
    patched = original.decode().replace(
        "__version__ = 'dev'", f"__version__ = '{VERSION}'"
    )
    patched = patched.replace(
        "BazelExtension('//mediapipe/tasks/c:libmediapipe.so')",
        "BazelExtension('//mediapipe/tasks/c:libmediapipe.dylib')",
    )
    if (
        f"__version__ = '{VERSION}'" not in patched
        or "BazelExtension('//mediapipe/tasks/c:libmediapipe.dylib')" not in patched
    ):
        raise RuntimeError("Unexpected upstream setup.py")
    with tempfile.TemporaryDirectory(prefix="wheel-", dir=cache) as scratch:
        work = Path(scratch)
        build_lib = work / "lib"
        raw = work / "raw"
        repaired = work / "repaired"
        setup.write_text(patched)
        try:
            run(
                [
                    sys.executable,
                    "setup.py",
                    "build_py",
                    "--link-opencv",
                    f"--build-lib={build_lib}",
                ],
                source,
                package_env,
            )
            target = build_lib / "mediapipe/tasks/c/libmediapipe.dylib"
            shutil.copy2(
                source / "bazel-bin/mediapipe/tasks/c/libmediapipe.dylib", target
            )
            opencv = (source / "bazel-source").resolve().parents[1] / "external/opencv"
            licenses = build_lib / "mediapipe/tasks/c/licenses"
            licenses.mkdir()
            shutil.copy2(opencv / "LICENSE", licenses / "OpenCV-LICENSE.txt")
            for component, name in (
                ("libpng", "LICENSE"),
                ("libjpeg", "README"),
                ("libtiff", "COPYRIGHT"),
                ("openexr", "LICENSE"),
                ("zlib", "README"),
            ):
                shutil.copy2(
                    opencv / "3rdparty" / component / name,
                    licenses / f"{component}-{name}.txt",
                )
            run(
                [
                    sys.executable,
                    "setup.py",
                    "build",
                    f"--build-lib={build_lib}",
                    "bdist_wheel",
                    "--skip-build",
                    "--plat-name=macosx_11_0_arm64",
                    f"--dist-dir={raw}",
                ],
                source,
                package_env,
            )
        finally:
            # upstream BuildPy restores __init__.py and third_party/BUILD normally
            if (source / "mediapipe/__init__.py.backup").exists():
                run([sys.executable, "setup.py", "restore"], source, package_env)
            setup.write_bytes(original)
        (raw_wheel,) = raw.glob("*.whl")
        with zipfile.ZipFile(raw_wheel) as archive:
            native = [
                name
                for name in archive.namelist()
                if name.endswith((".so", ".dylib", ".pyd"))
            ]
            if native != ["mediapipe/tasks/c/libmediapipe.dylib"]:
                raise RuntimeError(
                    f"Unexpected native modules; cannot use py3-none tag: {native}"
                )
        run(
            [
                sys.executable,
                "-m",
                "delocate.cmd.delocate_wheel",
                "--require-archs=arm64",
                "-w",
                str(repaired),
                str(raw_wheel),
            ],
            source,
            package_env,
        )
        (repaired_wheel,) = repaired.glob("*.whl")
        run(
            [
                sys.executable,
                "-m",
                "wheel",
                "tags",
                "--python-tag=py3",
                "--abi-tag=none",
                str(repaired_wheel),
            ],
            source,
            package_env,
        )
        (tagged_wheel,) = repaired.glob("*-py3-none-*.whl")
        output.mkdir(parents=True, exist_ok=True)
        destination = output / tagged_wheel.name
        shutil.copy2(tagged_wheel, destination)
        print(f"Built {destination}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path.home() / "Library/Caches/webcam-mods/mediapipe-patched",
    )
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument(
        "--gpu", action="store_true", help="enable experimental Metal support"
    )
    args = parser.parse_args()
    if platform.system() != "Darwin" or platform.machine() != "arm64":
        parser.error("This build supports only macOS ARM64")
    output = args.output_dir or (
        REPO / "dist/mediapipe-metal" if args.gpu else REPO / "vendor/mediapipe"
    )
    if args.gpu and output.expanduser().resolve() == REPO / "vendor/mediapipe":
        parser.error("Use a separate output directory for experimental GPU wheels")
    cache = args.cache_dir.expanduser().resolve()
    cache.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ) | {"HERMETIC_PYTHON_VERSION": "3.11"}
    source = cache / "source"
    bazel = prepare_bazel(cache)
    prepare_source(source, env)
    build_native(bazel, cache, source, env, gpu=args.gpu)
    package_wheel(
        bazel, cache, source, output.expanduser().resolve(), env, gpu=args.gpu
    )


if __name__ == "__main__":
    main()
