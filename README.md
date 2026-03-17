<p align="center">
  <img src="logo.png" alt="Fire Voice" width="180" />
</p>

<h1 align="center">🔥 Fire Voice</h1>

<p align="center">
  <strong>A blazing-fast, fully local voice-to-text tool for macOS.</strong><br/>
  Hold a key, speak, release — your words appear instantly.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/platform-macOS-lightgrey" alt="macOS" />
  <img src="https://img.shields.io/badge/engine-Faster--Whisper-orange" alt="Faster-Whisper" />
  <img src="https://img.shields.io/badge/privacy-100%25_local-green" alt="100% Local" />
  <img src="https://img.shields.io/badge/license-MIT-blue" alt="MIT License" />
</p>

---

## ✨ Features

- **100% Local & Private**: All transcription is done on your machine. No audio data or transcripts are ever sent to external APIs.
- **High Accuracy**: Uses the `small` Whisper model by default for high-quality Japanese and technical term recognition.
- **Visual Status Overlay**: A floating pill-shaped widget at the bottom of the screen shows the current state (idle / recording / analyzing) with smooth animations.
- **Auto-Mute** *(macOS only)*: Automatically mutes your system audio while recording to prevent speakers from interfering with your voice.
- **Custom Replacements**: Automatically fix common misspellings or enforce styling (e.g., "ジェミニ" -> "Gemini") via `voice-replacements.json`.
- **Privacy First**: Audio files are deleted immediately after transcription. No text logs are stored after stopping the service.
- **Fast Input**: Paste-based input ensures quick and reliable text insertion into any application.

## 🛠️ Setup

### Quick Install (recommended)

```bash
# 1. Install pipx (skip if already installed)
brew install pipx
pipx ensurepath

# 2. Restart your terminal, then install FireVoice
pipx install git+https://github.com/cshiraga/firevoice.git
```

That's it! The `firevoice` command is now available globally.

> **Note**: On macOS, you may need to grant Accessibility permissions to your Terminal/Python when first prompted.

## 🚀 How to Use

Control the background service using `firevoice` subcommands:

```bash
firevoice start     # Start the background service
firevoice status    # Check if it's running
firevoice stop      # Stop and clean up logs
firevoice restart   # Apply changes (e.g., after editing replacements)
firevoice logs      # Show recent log output
firevoice run       # Run in foreground (for debugging)
```

### Recording

1. **Press and hold** the `fn` (or globe) key on your keyboard.
2. **Speak** your message clearly.
3. **Release** the key to transcribe and paste the text automatically.

## 💡 Tips for Better Accuracy

If the transcription accuracy is not as expected, try the following:

- **Use a Dedicated Microphone**: Built-in laptop microphones often pick up fan noise and keyboard vibrations. A dedicated unidirectional (cardioid) USB microphone will significantly improve recognition.
- **Adjust System Input Volume**: Go to your OS Sound Settings and ensure the input volume is high enough (around 70-80%) so your voice is clearly captured without clipping.
- **Speak Clearly**: While Faster-Whisper is robust, speaking at a consistent volume and pace helps the model identify words more accurately.
- **Try a Larger Model**: If you have enough RAM (16GB+), you can try changing the `model_size` to `medium` in `main.py` for even higher accuracy.

## ⚙️ Configuration

### Custom Dictionary (Replacements)

A default `voice-replacements.json` file is automatically created in `~/.firevoice/` on first run. It is specifically optimized for **Japanese developers** to:
- Convert Katakana technical terms to English (e.g., "ジェミニ" -> "Gemini", "ギットハブ" -> "GitHub").
- Expand abbreviations (e.g., "プルリク" -> "PR").
- Insert symbols from spoken words (e.g., "スラッシュ" -> "/").

Feel free to modify `~/.firevoice/voice-replacements.json` to suit your own workflow or language.

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `VOICE_TRIGGER_KEY` | Trigger key to start recording | `fn` |
| `WHISPER_MODEL` | Whisper model size (`base`, `small`, `medium`) | `small` |
| `VOICE_OUTPUT_MODE` | Output method (`paste` or `type`) | `paste` |
| `VOICE_REPLACEMENTS_FILE` | Path to custom replacements JSON | `~/.firevoice/voice-replacements.json` |
| `VOICE_MUTE_DURING_RECORDING` | Mute system audio while recording | `true` |

## 🔄 Updating

```bash
pipx install --force git+https://github.com/cshiraga/firevoice.git
firevoice restart
```

To use a newer or larger Whisper model (e.g., `medium`, `large-v3`), set the `WHISPER_MODEL` environment variable. The model will be downloaded automatically on first use.

## 🗑️ Uninstalling

```bash
pipx uninstall firevoice
rm -rf ~/.firevoice   # remove config and logs (optional)
```

## 🔒 Security & Privacy

- **No Cloud Latency/Cost**: No API keys required.
- **Auto-Cleanup**: Log files are deleted on service stop/restart.
- **Transcription Logs**: For privacy, the transcribed text is **not** written to the system logs by default.

## 📄 License

This project is licensed under the [MIT License](LICENSE).
