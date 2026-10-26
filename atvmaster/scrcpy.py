"""Lanzador de scrcpy (escritorio remoto: espejo de pantalla con ratón y teclado)."""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass


@dataclass
class ScrcpyOptions:
    max_size: int = 0
    bitrate_mbps: int = 8
    max_fps: int = 30
    no_audio: bool = True
    stay_awake: bool = True
    screen_off: bool = False
    fullscreen: bool = False
    always_on_top: bool = False
    record_path: str = ""

    def to_args(self) -> list[str]:
        a = [f"--video-bit-rate={self.bitrate_mbps}M", f"--max-fps={self.max_fps}"]
        if self.max_size:
            a.append(f"--max-size={self.max_size}")
        if self.no_audio:
            a.append("--no-audio")
        if self.stay_awake:
            a.append("--stay-awake")
        if self.screen_off:
            a.append("--turn-screen-off")
        if self.fullscreen:
            a.append("--fullscreen")
        if self.always_on_top:
            a.append("--always-on-top")
        if self.record_path:
            a.append(f"--record={self.record_path}")
        return a


def launch(scrcpy_path: str, adb_path: str, serial: str, title: str,
           opts: ScrcpyOptions) -> subprocess.Popen:
    env = dict(os.environ, ADB=adb_path)
    cmd = [scrcpy_path, "-s", serial, f"--window-title={title}"] + opts.to_args()
    flags = 0x08000000 if os.name == "nt" else 0  # CREATE_NO_WINDOW
    return subprocess.Popen(cmd, env=env, creationflags=flags,
                            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
