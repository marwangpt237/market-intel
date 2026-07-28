import { Message, ToolCall } from '../types';

// Simulated agent service (replace later with real OpenCode server or LLM)
export class AgentService {
  private static instance: AgentService;

  static getInstance(): AgentService {
    if (!AgentService.instance) {
      AgentService.instance = new AgentService();
    }
    return AgentService.instance;
  }

  async processMessage(
    userMessage: string,
    onStream: (chunk: string) => void,
    onToolCall?: (tool: ToolCall) => void
  ): Promise<{ content: string; toolCalls?: ToolCall[] }> {
    // Simulate typing delay
    await new Promise((resolve) => setTimeout(resolve, 600));

    const lowerMsg = userMessage.toLowerCase();

    // Simple rule-based agent for demo (will be replaced with real LLM/OpenCode)
    let response = '';
    let toolCalls: ToolCall[] = [];

    if (lowerMsg.includes('create') && (lowerMsg.includes('file') || lowerMsg.includes('website') || lowerMsg.includes('html'))) {
      response = `I'll create that for you right away.`;
      const tool: ToolCall = {
        id: `tool-${Date.now()}`,
        name: 'create_file',
        args: { filename: lowerMsg.includes('website') ? 'index.html' : 'script.py', content: '...' },
        status: 'pending',
      };
      toolCalls.push(tool);
      if (onToolCall) onToolCall(tool);
    } 
    else if (lowerMsg.includes('run') || lowerMsg.includes('command') || lowerMsg.includes('terminal')) {
      response = `Running command in workspace...`;
      const tool: ToolCall = {
        id: `tool-${Date.now()}`,
        name: 'run_command',
        args: { command: userMessage.replace(/run|command/gi, '').trim() },
        status: 'pending',
      };
      toolCalls.push(tool);
      if (onToolCall) onToolCall(tool);
    } 
    else if (lowerMsg.includes('image') || lowerMsg.includes('ocr') || lowerMsg.includes('read')) {
      response = `I'll analyze the image for you.`;
      const tool: ToolCall = {
        id: `tool-${Date.now()}`,
        name: 'read_image',
        args: { action: 'ocr' },
        status: 'pending',
      };
      toolCalls.push(tool);
      if (onToolCall) onToolCall(tool);
    } 
    else if (lowerMsg.includes('list') && lowerMsg.includes('app')) {
      response = `Here are your installed apps:`;
      const tool: ToolCall = {
        id: `tool-${Date.now()}`,
        name: 'list_apps',
        args: {},
        status: 'pending',
      };
      toolCalls.push(tool);
      if (onToolCall) onToolCall(tool);
    } 
    else {
      // Generic helpful response
      response = `Understood. I'm Agent47 — your mobile AI agent. I can help with coding, file management, image OCR, running commands, launching apps, and more.\n\nTry asking me to:\n• Create a simple website\n• Write a Python script\n• Read text from an image\n• Run a terminal command`;
    }

    // Simulate streaming
    const words = response.split(' ');
    let streamed = '';
    for (let i = 0; i < words.length; i++) {
      streamed += words[i] + ' ';
      onStream(streamed.trim());
      await new Promise((r) => setTimeout(r, 35));
    }

    return { content: response, toolCalls };
  }

  // Simulate executing a tool (placeholder)
  async executeTool(toolCall: ToolCall): Promise<string> {
    await new Promise((r) => setTimeout(r, 1200));

    switch (toolCall.name) {
      case 'create_file':
        return `✅ File created successfully: ${toolCall.args.filename || 'new-file.txt'}`;
      case 'run_command':
        return `✅ Command executed:\n$ ${toolCall.args.command}\nOutput: Success`;
      case 'read_image':
        return `✅ OCR Result: "Hello from the screenshot! Agent47 can read this text easily."`;
      case 'list_apps':
        return `✅ Installed apps:\n• WhatsApp\n• Chrome\n• VS Code\n• Agent47`;
      default:
        return `✅ Tool "${toolCall.name}" completed successfully.`;
    }
  }
}