# DC Video Splitter

Split and compress gaming videos for Discord uploads. Windows desktop app — pick a video, set a max file size, get numbered clips ready to upload.

## For you (building)

### Prerequisites

- Python 3.9+
- Windows

### 1. Download FFmpeg

Download a Windows **gpl** static build from [BtbN FFmpeg Builds](https://github.com/BtbN/FFmpeg-Builds/releases) (e.g. `ffmpeg-master-latest-win64-gpl.zip`).

Extract and copy into the `ffmpeg/` folder:

```
ffmpeg/
  ffmpeg.exe
  ffprobe.exe
```

### 2. Install dependencies

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Run in development

```bat
python src\main.py
```

### 4. Build standalone exe

```bat
build.bat
```

Output: `dist\DCVideoSplitter\DCVideoSplitter.exe` (~300 MB folder with bundled FFmpeg)

Zip the entire `dist\DCVideoSplitter\` folder and send it to your friend.

## For your friend (using)

1. Unzip the folder anywhere
2. Run `DCVideoSplitter.exe`
3. Pick a video, set Discord file size limit, click Start
4. Upload the output files from the output folder

No Python or FFmpeg install required.
