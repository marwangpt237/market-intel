import React, { useState } from 'react';
import { StatusBar } from 'expo-status-bar';
import { SafeAreaProvider } from 'react-native-safe-area-context';
import { View, Text, TouchableOpacity, StyleSheet } from 'react-native';
import { ChatScreen } from './src/screens/ChatScreen';
import { WorkspaceScreen } from './src/screens/WorkspaceScreen';
import { ToolsScreen } from './src/screens/ToolsScreen';
import { MessageCircle, Folder, Wrench } from 'lucide-react-native';

type Tab = 'chat' | 'workspace' | 'tools';

export default function App() {
  const [activeTab, setActiveTab] = useState<Tab>('chat');

  const renderScreen = () => {
    switch (activeTab) {
      case 'chat':
        return <ChatScreen />;
      case 'workspace':
        return <WorkspaceScreen />;
      case 'tools':
        return <ToolsScreen />;
      default:
        return <ChatScreen />;
    }
  };

  return (
    <SafeAreaProvider>
      <StatusBar style="light" backgroundColor="#0A0F1C" />
      
      <View style={styles.container}>
        {renderScreen()}
      </View>

      {/* Bottom Tab Bar */}
      <View style={styles.tabBar}>
        <TouchableOpacity
          style={styles.tabItem}
          onPress={() => setActiveTab('chat')}
        >
          <MessageCircle 
            size={24} 
            color={activeTab === 'chat' ? '#3B82F6' : '#6B7280'} 
          />
          <Text style={[styles.tabLabel, activeTab === 'chat' && styles.tabLabelActive]}>
            Chat
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.tabItem}
          onPress={() => setActiveTab('workspace')}
        >
          <Folder 
            size={24} 
            color={activeTab === 'workspace' ? '#3B82F6' : '#6B7280'} 
          />
          <Text style={[styles.tabLabel, activeTab === 'workspace' && styles.tabLabelActive]}>
            Workspace
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={styles.tabItem}
          onPress={() => setActiveTab('tools')}
        >
          <Wrench 
            size={24} 
            color={activeTab === 'tools' ? '#3B82F6' : '#6B7280'} 
          />
          <Text style={[styles.tabLabel, activeTab === 'tools' && styles.tabLabelActive]}>
            Tools
          </Text>
        </TouchableOpacity>
      </View>
    </SafeAreaProvider>
  );
}

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0A0F1C',
  },
  tabBar: {
    flexDirection: 'row',
    backgroundColor: '#111827',
    borderTopWidth: 1,
    borderTopColor: '#1F2937',
    paddingBottom: 8,
    paddingTop: 8,
  },
  tabItem: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    paddingVertical: 4,
  },
  tabLabel: {
    color: '#6B7280',
    fontSize: 11,
    marginTop: 4,
    fontWeight: '500',
  },
  tabLabelActive: {
    color: '#3B82F6',
  },
});