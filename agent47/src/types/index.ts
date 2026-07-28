export interface Message {
  id: string;
  role: 'user' | 'assistant' | 'system' | 'tool';
  content: string;
  timestamp: number;
  attachments?: Attachment[];
  toolCalls?: ToolCall[];
}

export interface Attachment {
  id: string;
  type: 'image' | 'file' | 'text';
  uri: string;
  name: string;
  size?: number;
  mimeType?: string;
}

export interface ToolCall {
  id: string;
  name: string;
  args: Record<string, any>;
  result?: string;
  status: 'pending' | 'running' | 'success' | 'error';
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: Message[];
  workspacePath: string; // e.g. "workspace/session-123"
}

export interface FileItem {
  id: string;
  name: string;
  path: string;
  type: 'file' | 'directory';
  size?: number;
  lastModified: number;
  content?: string;
  mimeType?: string;
}

export interface Tool {
  id: string;
  name: string;
  description: string;
  icon: string;
  category: 'code' | 'file' | 'image' | 'system' | 'web' | 'other';
  available: boolean;
}