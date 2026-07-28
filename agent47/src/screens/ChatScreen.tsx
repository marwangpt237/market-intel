import React, { useState, useRef, useEffect } from 'react';
import {
  View,
  FlatList,
  StyleSheet,
  SafeAreaView,
  KeyboardAvoidingView,
  Platform,
  Text,
  TouchableOpacity,
} from 'react-native';
import { useAgentStore } from '../store/agentStore';
import { ChatBubble } from '../components/ChatBubble';
import { MessageInput } from '../components/MessageInput';
import { AgentService } from '../services/agentService';
import { Message, ToolCall } from '../types';
import { Plus, Menu } from 'lucide-react-native';

export const ChatScreen: React.FC = () => {
  const {
    sessions,
    currentSessionId,
    createSession,
    setCurrentSession,
    addMessage,
    updateMessage,
    isProcessing,
    setProcessing,
  } = useAgentStore();

  const [inputDisabled, setInputDisabled] = useState(false);
  const flatListRef = useRef<FlatList>(null);
  const agentService = AgentService.getInstance();

  const currentSession = sessions.find((s) => s.id === currentSessionId);

  // Auto-create first session
  useEffect(() => {
    if (sessions.length === 0) {
      createSession();
    }
  }, [sessions.length]);

  const scrollToBottom = () => {
    setTimeout(() => {
      flatListRef.current?.scrollToEnd({ animated: true });
    }, 100);
  };

  const handleSend = async (text: string) => {
    if (!currentSessionId) return;

    // Add user message
    addMessage(currentSessionId, {
      role: 'user',
      content: text,
    });

    scrollToBottom();
    setProcessing(true);
    setInputDisabled(true);

    // Add temporary assistant message for streaming
    const tempAssistantId = `msg-temp-${Date.now()}`;
    addMessage(currentSessionId, {
      role: 'assistant',
      content: '',
    });

    let streamedContent = '';
    let finalToolCalls: ToolCall[] = [];

    try {
      const result = await agentService.processMessage(
        text,
        (chunk) => {
          streamedContent = chunk;
          // Update the last message (assistant)
          const lastMsg = useAgentStore.getState().sessions
            .find(s => s.id === currentSessionId)?.messages.slice(-1)[0];
          
          if (lastMsg) {
            updateMessage(currentSessionId, lastMsg.id, { content: streamedContent });
          }
          scrollToBottom();
        },
        (tool) => {
          finalToolCalls.push(tool);
        }
      );

      // Update final assistant message
      const currentMessages = useAgentStore.getState().sessions
        .find(s => s.id === currentSessionId)?.messages || [];
      const lastAssistantMsg = currentMessages.filter(m => m.role === 'assistant').pop();

      if (lastAssistantMsg) {
        updateMessage(currentSessionId, lastAssistantMsg.id, {
          content: result.content,
          toolCalls: result.toolCalls || finalToolCalls,
        });
      }

      // Simulate tool execution if any
      if (result.toolCalls && result.toolCalls.length > 0) {
        for (const tool of result.toolCalls) {
          const updatedTool = { ...tool, status: 'running' as const };
          
          // Update tool status in message
          updateMessage(currentSessionId, lastAssistantMsg!.id, {
            toolCalls: [updatedTool],
          });

          const toolResult = await agentService.executeTool(tool);

          updateMessage(currentSessionId, lastAssistantMsg!.id, {
            toolCalls: [{ ...updatedTool, status: 'success', result: toolResult }],
          });

          // Add result as a tool message
          addMessage(currentSessionId, {
            role: 'tool',
            content: toolResult,
          });
        }
      }

    } catch (error) {
      console.error('Agent error:', error);
      addMessage(currentSessionId, {
        role: 'assistant',
        content: 'Sorry, I encountered an error. Please try again.',
      });
    } finally {
      setProcessing(false);
      setInputDisabled(false);
      scrollToBottom();
    }
  };

  const handleAttach = () => {
    // TODO: Implement image/document picker
    console.log('Attach pressed - TODO: image picker');
  };

  if (!currentSession) {
    return (
      <View style={styles.emptyContainer}>
        <Text style={styles.emptyText}>Loading...</Text>
      </View>
    );
  }

  return (
    <SafeAreaView style={styles.container}>
      <KeyboardAvoidingView
        behavior={Platform.OS === 'ios' ? 'padding' : 'height'}
        style={styles.keyboardView}
        keyboardVerticalOffset={Platform.OS === 'ios' ? 90 : 0}
      >
        {/* Header */}
        <View style={styles.header}>
          <TouchableOpacity onPress={() => {}}>
            <Menu size={24} color="#9CA3AF" />
          </TouchableOpacity>
          <Text style={styles.headerTitle} numberOfLines={1}>
            {currentSession.title}
          </Text>
          <TouchableOpacity onPress={() => createSession()}>
            <Plus size={24} color="#3B82F6" />
          </TouchableOpacity>
        </View>

        {/* Messages */}
        <FlatList
          ref={flatListRef}
          data={currentSession.messages}
          keyExtractor={(item) => item.id}
          renderItem={({ item }) => (
            <ChatBubble
              message={item}
              onToolPress={(tool) => console.log('Tool pressed:', tool)}
            />
          )}
          contentContainerStyle={styles.messagesContainer}
          onContentSizeChange={scrollToBottom}
        />

        {/* Input */}
        <MessageInput
          onSend={handleSend}
          onAttach={handleAttach}
          disabled={isProcessing || inputDisabled}
        />
      </KeyboardAvoidingView>
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0A0F1C',
  },
  keyboardView: {
    flex: 1,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    justifyContent: 'space-between',
    paddingHorizontal: 16,
    paddingVertical: 12,
    borderBottomWidth: 1,
    borderBottomColor: '#1F2937',
    backgroundColor: '#0A0F1C',
  },
  headerTitle: {
    color: '#F3F4F6',
    fontSize: 18,
    fontWeight: '600',
    flex: 1,
    textAlign: 'center',
    marginHorizontal: 12,
  },
  messagesContainer: {
    paddingHorizontal: 16,
    paddingBottom: 20,
    flexGrow: 1,
  },
  emptyContainer: {
    flex: 1,
    justifyContent: 'center',
    alignItems: 'center',
    backgroundColor: '#0A0F1C',
  },
  emptyText: {
    color: '#6B7280',
    fontSize: 16,
  },
});