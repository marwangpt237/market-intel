import { create } from 'zustand';
import { ChatSession, Message, FileItem, Tool } from '../types';

interface AgentState {
  sessions: ChatSession[];
  currentSessionId: string | null;
  isProcessing: boolean;
  workspaceFiles: Record<string, FileItem[]>; // sessionId -> files

  // Actions
  createSession: () => ChatSession;
  setCurrentSession: (id: string) => void;
  addMessage: (sessionId: string, message: Omit<Message, 'id' | 'timestamp'>) => void;
  updateMessage: (sessionId: string, messageId: string, updates: Partial<Message>) => void;
  deleteSession: (id: string) => void;

  // Workspace
  addFile: (sessionId: string, file: Omit<FileItem, 'id' | 'lastModified'>) => void;
  updateFile: (sessionId: string, fileId: string, updates: Partial<FileItem>) => void;
  deleteFile: (sessionId: string, fileId: string) => void;
  getFilesForSession: (sessionId: string) => FileItem[];

  // Agent status
  setProcessing: (processing: boolean) => void;

  // Demo tools
  availableTools: Tool[];
}

const initialTools: Tool[] = [
  { id: 'write_code', name: 'Write Code', description: 'Create or edit source files', icon: 'code', category: 'code', available: true },
  { id: 'run_command', name: 'Run Command', description: 'Execute terminal commands', icon: 'terminal', category: 'system', available: true },
  { id: 'read_image', name: 'Read Image (OCR)', description: 'Extract text from image', icon: 'image', category: 'image', available: true },
  { id: 'create_file', name: 'Create File', description: 'Write a new file in workspace', icon: 'file-plus', category: 'file', available: true },
  { id: 'list_apps', name: 'List Apps', description: 'Show installed apps', icon: 'smartphone', category: 'system', available: true },
  { id: 'open_app', name: 'Open App', description: 'Launch an app by name', icon: 'play', category: 'system', available: true },
  { id: 'download', name: 'Download File', description: 'Download from URL', icon: 'download', category: 'web', available: true },
];

export const useAgentStore = create<AgentState>((set, get) => ({
  sessions: [],
  currentSessionId: null,
  isProcessing: false,
  workspaceFiles: {},
  availableTools: initialTools,

  createSession: () => {
    const id = `session-${Date.now()}`;
    const newSession: ChatSession = {
      id,
      title: 'New Chat',
      createdAt: Date.now(),
      updatedAt: Date.now(),
      messages: [
        {
          id: `msg-${Date.now()}`,
          role: 'system',
          content: 'Hello! I\'m Agent47. How can I help you today? I can write code, run commands, work with files, read images, and more.',
          timestamp: Date.now(),
        },
      ],
      workspacePath: `workspace/${id}`,
    };

    set((state) => ({
      sessions: [...state.sessions, newSession],
      currentSessionId: id,
      workspaceFiles: {
        ...state.workspaceFiles,
        [id]: [],
      },
    }));

    return newSession;
  },

  setCurrentSession: (id) => {
    set({ currentSessionId: id });
  },

  addMessage: (sessionId, messageData) => {
    const message: Message = {
      ...messageData,
      id: `msg-${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
      timestamp: Date.now(),
    };

    set((state) => {
      const updatedSessions = state.sessions.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              messages: [...session.messages, message],
              updatedAt: Date.now(),
              title: session.messages.length === 1 && message.role === 'user' 
                ? message.content.substring(0, 40) + (message.content.length > 40 ? '...' : '')
                : session.title,
            }
          : session
      );

      return { sessions: updatedSessions };
    });
  },

  updateMessage: (sessionId, messageId, updates) => {
    set((state) => ({
      sessions: state.sessions.map((session) =>
        session.id === sessionId
          ? {
              ...session,
              messages: session.messages.map((msg) =>
                msg.id === messageId ? { ...msg, ...updates } : msg
              ),
            }
          : session
      ),
    }));
  },

  deleteSession: (id) => {
    set((state) => {
      const newSessions = state.sessions.filter((s) => s.id !== id);
      const newCurrent = state.currentSessionId === id 
        ? (newSessions.length > 0 ? newSessions[0].id : null) 
        : state.currentSessionId;

      const { [id]: _, ...restFiles } = state.workspaceFiles;

      return {
        sessions: newSessions,
        currentSessionId: newCurrent,
        workspaceFiles: restFiles,
      };
    });
  },

  addFile: (sessionId, fileData) => {
    const file: FileItem = {
      ...fileData,
      id: `file-${Date.now()}`,
      lastModified: Date.now(),
    };

    set((state) => ({
      workspaceFiles: {
        ...state.workspaceFiles,
        [sessionId]: [...(state.workspaceFiles[sessionId] || []), file],
      },
    }));
  },

  updateFile: (sessionId, fileId, updates) => {
    set((state) => ({
      workspaceFiles: {
        ...state.workspaceFiles,
        [sessionId]: (state.workspaceFiles[sessionId] || []).map((file) =>
          file.id === fileId ? { ...file, ...updates, lastModified: Date.now() } : file
        ),
      },
    }));
  },

  deleteFile: (sessionId, fileId) => {
    set((state) => ({
      workspaceFiles: {
        ...state.workspaceFiles,
        [sessionId]: (state.workspaceFiles[sessionId] || []).filter((f) => f.id !== fileId),
      },
    }));
  },

  getFilesForSession: (sessionId) => {
    return get().workspaceFiles[sessionId] || [];
  },

  setProcessing: (processing) => set({ isProcessing: processing }),
}));