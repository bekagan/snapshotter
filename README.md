# Snapshotter

Snapshotter is a small Linux desktop app that downloads videos from YouTube and X (Twitter)
as MP4.

Open the app, paste a YouTube link or an X (Twitter) post link, and click **Download Video**.
The video is saved to your `~/Downloads` folder.

If an X post has more than one video, Snapshotter downloads the first one. To get a different
video, open it on X and copy its link. The link ends in `/video/2`, `/video/3` and so on.
Only public posts work: posts marked as sensitive and posts from private accounts need a
signed-in account, which Snapshotter doesn't support.

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
