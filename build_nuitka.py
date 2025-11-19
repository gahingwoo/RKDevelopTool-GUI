#!/usr/bin/env python3
import os
import sys
import subprocess
import platform
from pathlib import Path

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
    
    # Base compilation command
    cmd = [
        sys.executable, "-m", "nuitka",
        "--standalone",
        "--onefile", 
        "--follow-imports",
        "--remove-output",
        "--assume-yes-for-downloads",
        "--output-filename=rkdeveloptool-gui",
        "--lto=yes",
        f"--jobs={os.cpu_count() or 4}",
        "--quiet",
    ]
    
    # Platform-specific options
    system = platform.system().lower()
    if system == "darwin":  # macOS
        cmd.extend([
            "--macos-create-app-bundle",
            "--macos-app-name=RKDevelopTool-GUI",
            "--macos-app-icon=none",
            "--include-module=PyQt6",
            "--include-module=PyQt6.QtCore",
            "--include-module=PyQt6.QtGui",
            "--include-module=PyQt6.QtWidgets",
            "--disable-console",
            "--macos-disable-console-window",
        ])
    else:  # Linux
        cmd.append("--enable-plugin=pyqt6")
    
    # Include necessary files
    if os.path.exists("i18n.py"):
        cmd.extend(["--include-data-file=./i18n.py=i18n.py"])
    if os.path.exists("readme.md"):
        cmd.extend(["--include-data-file=./readme.md=readme.md"])
    
    # Add main script
    cmd.append("rkdevtoolgui.py")
    
    # Execute compilation
    print(f"Building RKDevelopTool-GUI ({platform.system()})...")
    
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=1800)
        print("Build successful!")
        
        # Show generated file info
        output_dir = Path("dist")
        if output_dir.exists():
            for item in output_dir.iterdir():
                if item.is_file():
                    size = item.stat().st_size / (1024 * 1024)  # MB
                    print(f"Output: {item.name} ({size:.2f} MB)")
        
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"Build failed! Exit code: {e.returncode}")
        if e.stderr:
            print(f"Error: {e.stderr[:500]}...")
        return False
    except subprocess.TimeoutExpired:
        print("Build timeout (30 minutes)")
        return False

if __name__ == "__main__":
    success = build_with_nuitka()
    sys.exit(0 if success else 1)