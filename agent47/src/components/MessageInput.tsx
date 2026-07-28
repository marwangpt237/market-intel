import React, { useState } from 'react';
import {
  View,
  TextInput,
  TouchableOpacity,
  StyleSheet,
  Keyboard,
} from 'react-native';
import { Send, Paperclip, Mic } from 'lucide-react-native';

interface MessageInputProps {
  onSend: (text: string) => void;
  onAttach?: () => void;
  disabled?: boolean;
}

export const MessageInput: React.FC<MessageInputProps> = ({
  onSend,
  onAttach,
  disabled = false,
}) => {
  const [text, setText] = useState('');

  const handleSend = () => {
    if (text.trim() && !disabled) {
      onSend(text.trim());
      setText('');
      Keyboard.dismiss();
    }
  };

  return (
    <View style={styles.container}>
      <TouchableOpacity onPress={onAttach} style={styles.iconButton}>
        <Paperclip size={22} color="#9CA3AF" />
      </TouchableOpacity>

      <TextInput
        style={styles.input}
        placeholder="Ask Agent47 anything..."
        placeholderTextColor="#6B7280"
        value={text}
        onChangeText={setText}
        multiline
        maxLength={2000}
        editable={!disabled}
      />

      <TouchableOpacity
        onPress={handleSend}
        disabled={!text.trim() || disabled}
        style={[styles.sendButton, (!text.trim() || disabled) && styles.sendButtonDisabled]}
      >
        <Send size={20} color={text.trim() && !disabled ? '#FFFFFF' : '#6B7280'} />
      </TouchableOpacity>
    </View>
  );
};

const styles = StyleSheet.create({
  container: {
    flexDirection: 'row',
    alignItems: 'flex-end',
    backgroundColor: '#1F2937',
    borderRadius: 24,
    paddingHorizontal: 12,
    paddingVertical: 8,
    margin: 12,
    marginBottom: 20,
  },
  input: {
    flex: 1,
    color: '#F3F4F6',
    fontSize: 16,
    maxHeight: 120,
    paddingHorizontal: 12,
    paddingVertical: 8,
  },
  iconButton: {
    padding: 8,
    justifyContent: 'center',
    alignItems: 'center',
  },
  sendButton: {
    backgroundColor: '#3B82F6',
    width: 40,
    height: 40,
    borderRadius: 20,
    justifyContent: 'center',
    alignItems: 'center',
    marginLeft: 4,
  },
  sendButtonDisabled: {
    backgroundColor: '#374151',
  },
});