# Care Agent v4.0 - Windows Package

## Option A: Run NOW (Installer - Recommended)
1. Double-click `CareAgent-Install.bat`
2. Wait 3-5 min for libraries to install
3. Double-click `Launch-CareAgent.bat` (created by installer)
4. Browser opens to http://localhost:5000
5. Set your API key in Settings

Requires Python 3.9+ installed. Get it at https://python.org

## Option B: True .exe via GitHub Actions
1. Push this folder to GitHub (github.com/Cl4pp/care-agent)
2. Go to Actions tab in your repo
3. Run "Build Windows EXE" workflow
4. Download CareAgent.exe from Artifacts

The .exe bundles everything - no Python needed on target machine.

## API Keys
- Anthropic (Claude): https://console.anthropic.com
- OpenRouter (free tier): https://openrouter.ai
- Local/Free: Install Ollama (https://ollama.ai) - no key needed

## Features
- AI-powered caregiving assistant for Charis
- Daily schedule management
- Text-to-speech alerts
- Voice input (faster-whisper)
- Semantic memory (ChromaDB)
- ADHD-friendly design
