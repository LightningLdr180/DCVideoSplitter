# FFmpeg (not included in git)

This app needs **FFmpeg** as a separate download. Binaries are not committed to the repository.

## Setup

1. Download a Windows **gpl** static build from [BtbN FFmpeg Builds](https://github.com/BtbN/FFmpeg-Builds/releases)  
   (e.g. `ffmpeg-master-latest-win64-gpl.zip`).

2. Extract and copy **only these files** into this folder:

```
ffmpeg/
  ffmpeg.exe
  ffprobe.exe
  README.md          ← this file
```

Optional: include `LICENSE.txt` from the FFmpeg archive for distribution compliance.

## Development

From the project root:

```bat
python src\main.py
```

## Built app

After `build.bat`, the same `ffmpeg/` folder is copied next to `DCVideoSplitter.exe`:

```
dist\DCVideoSplitter\
  DCVideoSplitter.exe
  ffmpeg\
    ffmpeg.exe
    ffprobe.exe
```

You can **replace or upgrade FFmpeg** anytime by swapping files in this folder — no rebuild required.

## Troubleshooting

If the app says FFmpeg is missing, confirm both `.exe` files are directly in `ffmpeg/` (not in a nested `bin/` subfolder).
