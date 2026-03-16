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

1. **Clone the repository**:
   ```bash
   git clone https://github.com/cshiraga/voice-input.git
   cd voice-input
   ```

2. **Create a virtual environment**:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

   *Note: On macOS, you may need to grant Accessibility permissions to your Terminal/Python when first prompted.*

## 🚀 How to Use

Control the background service using the provided scripts:

```bash
./start   # Start the background service
./status  # Check if it's running
./stop    # Stop and clean up logs
./restart # Apply changes (e.g., after editing replacements)
./logs    # Show recent log output
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

The project includes a pre-configured `voice-replacements.json` file. It is specifically optimized for **Japanese developers** to:
- Convert Katakana technical terms to English (e.g., "ジェミニ" -> "Gemini", "ギットハブ" -> "GitHub").
- Expand abbreviations (e.g., "プルリク" -> "PR").
- Insert symbols from spoken words (e.g., "スラッシュ" -> "/").

Feel free to modify this file to suit your own workflow or language. If you don't need these replacements, you can simply clear the JSON object in that file.

### Environment Variables

| Variable | Description | Default |
|---|---|---|
| `VOICE_TRIGGER_KEY` | Trigger key to start recording | `fn` |
| `WHISPER_MODEL` | Whisper model size (`base`, `small`, `medium`) | `small` |
| `VOICE_OUTPUT_MODE` | Output method (`paste` or `type`) | `paste` |
| `VOICE_REPLACEMENTS_FILE` | Path to custom replacements JSON | `./voice-replacements.json` |
| `VOICE_MUTE_DURING_RECORDING` | Mute system audio while recording | `true` |
| `PYTHON_BIN` | Python executable path | `./.venv/bin/python` |

## 🔄 Updating

To get the latest model improvements and bug fixes, update the dependencies:

```bash
source .venv/bin/activate
pip install --upgrade -r requirements.txt
```

To use a newer or larger Whisper model (e.g., `medium`, `large-v3`), set the `WHISPER_MODEL` environment variable. The model will be downloaded automatically on first use.

## 🔒 Security & Privacy

- **No Cloud Latency/Cost**: No API keys required.
- **Auto-Cleanup**: Temporary `.wav` files and log files are deleted on service stop/restart.
- **Transcription Logs**: For privacy, the transcribed text is **not** written to the system logs by default.

## 📄 License

This project is licensed under the [MIT License](LICENSE).
