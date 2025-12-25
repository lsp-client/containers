import subprocess
import os
import shutil


def get_deps(binary):
    try:
        output = subprocess.check_output(
            [
                "docker",
                "run",
                "--rm",
                "--entrypoint",
                "ldd",
                "test-sourcekit-lsp",
                binary,
            ],
            stderr=subprocess.STDOUT,
        ).decode()
        deps = []
        for line in output.splitlines():
            if "=>" in line:
                path = line.split("=>")[1].split("(")[0].strip()
                if path and os.path.isabs(path):
                    deps.append(path)
            elif line.strip() and line.strip().startswith("/"):
                path = line.split("(")[0].strip()
                if path and os.path.isabs(path):
                    deps.append(path)
        return deps
    except Exception as e:
        print(f"Error getting deps for {binary}: {e}")
        return []


binaries = [
    "/usr/bin/sourcekit-lsp",
    "/usr/bin/swift-frontend",
    "/usr/bin/swift-package",
    "/usr/bin/swift-driver",
    "/usr/lib/libsourcekitdInProc.so",
]

all_deps = set()
for b in binaries:
    all_deps.update(get_deps(b))

for dep in sorted(all_deps):
    print(dep)
