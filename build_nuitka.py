#!/usr/bin/env python3
import os
import sys
import subprocess
import platform
import shutil
from pathlib import Path


def find_rkdeveloptool():
    """Find rkdeveloptool absolute path on the system"""
    try:
        result = subprocess.run(["which", "rkdeveloptool"],
                                capture_output=True, text=True, check=True)
        tool_path = result.stdout.strip()
        if tool_path and os.path.exists(tool_path):
            return tool_path
    except:
        pass

    # Common installation paths
    common_paths = [
        "/usr/local/bin/rkdeveloptool",
        "/usr/bin/rkdeveloptool",
        "/opt/homebrew/bin/rkdeveloptool",
        os.path.expanduser("~/.local/bin/rkdeveloptool"),
    ]

    for path in common_paths:
        if os.path.exists(path):
            return path

    return None


def patch_source_with_tool_path(tool_path):
    """Patch utils.py with absolute tool path for macOS .app"""
    if not tool_path:
        return False

    source_file = "utils.py"
    backup_file = "utils.py.backup"

    # Create backup
    shutil.copy2(source_file, backup_file)

    try:
        with open(source_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Replace RKTOOL = "rkdeveloptool" with absolute path
        old_line = 'RKTOOL = "rkdeveloptool"'
        new_line = f'RKTOOL = "{tool_path}"'

        if old_line in content:
            content = content.replace(old_line, new_line)

            with open(source_file, 'w', encoding='utf-8') as f:
                f.write(content)

            print(f"Patched utils.py with tool path: {tool_path}")
            return True
        else:
            print(f"Could not find line to patch in {source_file}")
            return False

    except Exception as e:
        print(f"Failed to patch source: {e}")
        # Restore backup
        if os.path.exists(backup_file):
            shutil.copy2(backup_file, source_file)
        return False


def restore_source():
    """Restore original source file"""
    backup_file = "utils.py.backup"
    source_file = "utils.py"

    if os.path.exists(backup_file):
        shutil.copy2(backup_file, source_file)
        os.remove(backup_file)
        print("Restored original source file")


def build_with_nuitka():
    """Build project using Nuitka"""
    # Check if Nuitka is installed
    try:
        subprocess.run([sys.executable, "-m", "nuitka", "--version"],
                       capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("Please install Nuitka first: pip install nuitka")
        return False

    # Create output directory
    os.makedirs("dist", exist_ok=True)

    system = platform.system().lower()
    patched = False

    # For macOS .app bundle, patch source with absolute tool path
    if system == "darwin":
        tool_path = find_rkdeveloptool()
        if tool_path:
            print(f"Found rkdeveloptool at: {tool_path}")
            patched = patch_source_with_tool_path(tool_path)
            if not patched:
                print("Building without patched path - tool may not work in .app")
        else:
            print("rkdeveloptool not found - .app may not function properly")
            print("Install it with: brew install rkdeveloptool")

    try:
        # Base compilation command
        cmd = [
            sys.executable, "-m", "nuitka",
            "--follow-imports",
            "--enable-plugin=pyside6",
            "--remove-output",
            "--assume-yes-for-downloads",
            "--output-dir=dist",
            "--lto=yes",
            f"--jobs={os.cpu_count() or 4}",
            "--quiet",
        ]

        # Platform-specific options
        if system == "darwin":  # macOS - .app bundle
            cmd.extend([
                "--standalone",
                "--macos-create-app-bundle",
                "--macos-app-name=RKDevelopTool-GUI",
                "--macos-app-icon=none",
            ])
        elif system == "linux":  # Linux - single file
            cmd.extend([
                "--onefile",
            ])

        # Include necessary files
        if os.path.exists("i18n.py"):
            cmd.extend(["--include-data-file=./i18n.py=i18n.py"])
        if os.path.exists("readme.md"):
            cmd.extend(["--include-data-file=./readme.md=readme.md"])

        # Add main script
        cmd.append("rkdevtoolgui.py")

        # Execute compilation
        print(f"Building RKDevelopTool-GUI ({platform.system()})...")

        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1800)
        print("Build successful!")

        # Show generated file info
        output_dir = Path("dist")
        if output_dir.exists():
            for item in output_dir.iterdir():
                if item.is_dir() and item.suffix == ".app":
                    print(f"Output: {item.name} (macOS App Bundle)")
                    print(f"Location: dist/{item.name}")
                elif item.is_file() and item.name == "rkdevtoolgui":
                    size = item.stat().st_size / (1024 * 1024)  # MB
                    print(f"Output: {item.name} ({size:.2f} MB)")
                    print(f"Location: dist/{item.name}")

        return True

    except subprocess.CalledProcessError as e:
        print(f"Build failed! Exit code: {e.returncode}")
        if e.stderr:
            print(f"Error: {e.stderr[:500]}...")
        return False
    except subprocess.TimeoutExpired:
        print("Build timeout (30 minutes)")
        return False
    finally:
        # Always restore original source if patched
        if patched:
            restore_source()


if __name__ == "__main__":
    success = build_with_nuitka()
    sys.exit(0 if success else 1)