import os
import subprocess
import json
from pathlib import Path


def get_changed_files(base_sha, head_sha, triple_dot=False):
    try:
        if triple_dot:
            cmd = ["git", "diff", "--name-only", f"{base_sha}...{head_sha}"]
        else:
            cmd = ["git", "diff", "--name-only", base_sha, head_sha]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.splitlines()
    except subprocess.CalledProcessError:
        return []


def main():
    event_name = os.environ.get("GITHUB_EVENT_NAME")

    if event_name == "pull_request":
        base_ref = os.environ.get("GITHUB_BASE_REF")
        # We assume origin/<base_ref> is fetched
        base_sha = f"origin/{base_ref}"
        head_sha = "HEAD"
        changed_files = get_changed_files(base_sha, head_sha, triple_dot=True)
    elif event_name == "workflow_dispatch":
        # For manual trigger, we compare with the previous commit to see what changed
        # Alternatively, we could rebuild everything, but comparing is more efficient
        base_sha = "HEAD^"
        head_sha = "HEAD"
        changed_files = get_changed_files(base_sha, head_sha)
    else:
        base_sha = os.environ.get("GITHUB_EVENT_BEFORE")
        head_sha = os.environ.get("GITHUB_SHA", "HEAD")

        if not base_sha or base_sha == "0000000000000000000000000000000000000000":
            # For new branches or initial push, compare with HEAD^
            # If that fails, it might be the first commit, so we return all images
            try:
                changed_files = get_changed_files("HEAD^", "HEAD")
            except:
                # First commit or something went wrong, rebuild all to be safe
                print(
                    json.dumps(
                        [
                            d.name
                            for d in Path(".").iterdir()
                            if d.is_dir() and (d / "ContainerFile").exists()
                        ]
                    )
                )
                return
        else:
            changed_files = get_changed_files(base_sha, head_sha)

    all_images = [
        d.name
        for d in Path(".").iterdir()
        if d.is_dir() and (d / "ContainerFile").exists()
    ]
    all_images.sort()

    global_triggers = ["registry.toml", "scripts/", ".github/workflows/"]

    rebuild_all = False
    for f in changed_files:
        if any(f.startswith(gt) for gt in global_triggers):
            rebuild_all = True
            break

    if rebuild_all:
        selected_images = all_images
    else:
        selected_images = []
        for img in all_images:
            if any(f.startswith(f"{img}/") for f in changed_files):
                selected_images.append(img)

    print(json.dumps(selected_images))


if __name__ == "__main__":
    main()
