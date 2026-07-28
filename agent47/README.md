# Agent47 — Mobile AI Agent

A powerful, open-source-inspired mobile AI agent app (similar to Reze AI / OpenCode Mobile).

Built with **React Native + Expo** for Android (and iOS/web).

## Features (MVP)

- **Chat Interface** — Natural language requests with streaming responses
- **Tool Calling** — Agent can run simulated / real tools: write code, create files, run commands, OCR, launch apps, download, image processing
- **Workspace** — Per-chat file system (create/edit/read files)
- **Multi-session** — Multiple chats with separate workspaces
- **Attachments** — Attach images (OCR), documents
- **Dark, clean UI** — Inspired by Reze AI screenshots
- **Local-first** — Uses a local agent simulation (can be connected to real OpenCode server or LLM API later)

## Tech Stack

- Expo SDK 57 + React Native 0.86
- React Navigation
- Zustand (state)
- Expo ImagePicker, FileSystem, DocumentPicker
- Lucide icons

## Quick Start

```bash
cd agent47
npm install
npx expo start
# Scan QR with Expo Go or run on Android emulator
```

## Architecture

```
agent47/
├── app/                 # (will be added for expo-router later)
├── src/
│   ├── components/      # ChatBubble, MessageInput, FileCard, ToolCard
│   ├── screens/         # Chat, Workspace, Tools, Settings
│   ├── store/           # zustand store: chats, messages, files, agent
│   ├── services/        # AgentService (tool executor + LLM interface)
│   ├── types/           # TypeScript models
│   └── utils/
├── assets/
└── App.tsx
```

## Roadmap (future phases)

- Real OpenCode server connection (HTTP + SSE)
- Actual terminal execution via WebSocket / local server
- Real LLM integration (OpenAI, Anthropic, local via Ollama)
- Git integration
- Background tasks & local server hosting
- iOS support

## License

MIT — based on the spirit of OpenCode (MIT)

---

This is the first version of **Agent47** — a mobile-first AI coding + productivity agent.