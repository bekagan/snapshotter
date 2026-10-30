# Snapshotter

Snapshotter is a small Linux desktop app that downloads YouTube videos as MP4.

Open the app, paste a YouTube link, and click **Download Video**. The video is saved to your
`~/Downloads` folder.

## Install

Open a terminal in this folder and run:

```bash
chmod +x install.sh uninstall.sh
./install.sh
```

The app is installed for your user only. You don't need `sudo` or root.

When the install finishes, search for **Snapshotter** in your application menu.
You can delete this folder afterwards.

### FFmpeg: choose your video quality

If FFmpeg isn't installed, the installer asks:

```
Install FFmpeg now with 'sudo apt-get install -y ffmpeg'? [y/N]
```

- **Answer `y`** for the best quality (1080p, 4K and so on). FFmpeg is installed, and this step
  asks for your password.
- **Answer `n`** if low quality (usually 360p) is enough. FFmpeg is not downloaded, nothing
  else is installed with `sudo`, and Snapshotter still works.

You can install FFmpeg later at any time. Snapshotter switches to the best quality automatically.

## Uninstall

```bash
./uninstall.sh
```

If you've already deleted this folder, run:

```bash
~/.local/share/snapshotter/uninstall.sh
```

Your downloaded videos are never deleted.
