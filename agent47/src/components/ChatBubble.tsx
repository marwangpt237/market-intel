import React from 'react';
import { View, Text, StyleSheet, TouchableOpacity } from 'react-native';
import { Message } from '../types';

interface ChatBubbleProps {
  message: Message;
  onToolPress?: (toolCall: any) => void;
}

export const ChatBubble: React.FC<ChatBubbleProps> = ({ message, onToolPress }) => {
  const isUser = message.role === 'user';
  const isSystem = message.role === 'system';
  const isTool = message.role === 'tool';

  if (isSystem) {
    return (
      <View style={styles.systemContainer}>
        <Text style={styles.systemText}>{message.content}</Text>
      </View>
    );
  }

  return (
    <View style={[styles.container, isUser ? styles.userContainer : styles.assistantContainer]}>
      <View style={[styles.bubble, isUser ? styles.userBubble : styles.assistantBubble]}>
        <Text style={[styles.text, isUser ? styles.userText : styles.assistantText]}>
          {message.content}
        </Text>

        {/* Tool Calls */}
        {message.toolCalls && message.toolCalls.length > 0 && (
          <View style={styles.toolContainer}>
            {message.toolCalls.map((tool, index) => (
              <TouchableOpacity
                key={index}
                style={styles.toolBadge}
                onPress={() => onToolPress?.(tool)}
              >
                <Text style={styles.toolText}>
                  🔧 {tool.name} {tool.status === 'running' ? '(running...)' : ''}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        )}

        {/* Attachments preview */}
        {message.attachments && message.attachments.length > 0 && (
          <View style={styles.attachmentContainer}>
            {message.attachments.map((att, idx) => (
              <View key={idx} style={styles.attachmentBadge}>
                <Text style={styles.attachmentText}>📎 {att.name}</Text>
              </View>
            ))}
          </View>
        )}
      </View>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    marginVertical: 4,
    maxWidth: '85%',
  },
  userContainer: {
    alignSelf: 'flex-end',
  },
  assistantContainer: {
    alignSelf: 'flex-start',
  },
  bubble: {
    borderRadius: 18,
    paddingHorizontal: 16,
    paddingVertical: 12,
    maxWidth: '100%',
  },
  userBubble: {
    backgroundColor: '#3B82F6',
    borderBottomRightRadius: 4,
  },
  assistantBubble: {
    backgroundColor: '#1F2937',
    borderBottomLeftRadius: 4,
  },
  text: {
    fontSize: 16,
    lineHeight: 22,
  },
  userText: {
    color: '#FFFFFF',
  },
  assistantText: {
    color: '#F3F4F6',
  },
  systemContainer: {
    alignSelf: 'center',
    backgroundColor: '#374151',
    paddingHorizontal: 14,
    paddingVertical: 8,
    borderRadius: 20,
    marginVertical: 8,
  },
  systemText: {
    color: '#9CA3AF',
    fontSize: 13,
    textAlign: 'center',
  },
  toolContainer: {
    marginTop: 8,
    gap: 4,
  },
  toolBadge: {
    backgroundColor: '#374151',
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 12,
    alignSelf: 'flex-start',
  },
  toolText: {
    color: '#60A5FA',
    fontSize: 13,
    fontWeight: '500',
  },
  attachmentContainer: {
    marginTop: 8,
  },
  attachmentBadge: {
    backgroundColor: '#4B5563',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 8,
    marginTop: 4,
  },
  attachmentText: {
    color: '#D1D5DB',
    fontSize: 12,
  },
});