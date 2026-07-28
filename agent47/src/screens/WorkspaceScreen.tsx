import React from 'react';
import {
  View,
  Text,
  FlatList,
  StyleSheet,
  TouchableOpacity,
  SafeAreaView,
} from 'react-native';
import { useAgentStore } from '../store/agentStore';
import { FileItem } from '../types';
import { FolderOpen, FileText, Plus } from 'lucide-react-native';

export const WorkspaceScreen: React.FC = () => {
  const { currentSessionId, getFilesForSession, addFile } = useAgentStore();

  const files = currentSessionId ? getFilesForSession(currentSessionId) : [];

  const handleCreateDemoFile = () => {
    if (!currentSessionId) return;

    addFile(currentSessionId, {
      name: `demo-${Date.now()}.txt`,
      path: `workspace/demo-${Date.now()}.txt`,
      type: 'file',
      content: 'This is a demo file created by Agent47.',
      mimeType: 'text/plain',
    });
  };

  const renderFile = ({ item }: { item: FileItem }) => (
    <TouchableOpacity style={styles.fileItem}>
      <View style={styles.fileIcon}>
        {item.type === 'directory' ? (
          <FolderOpen size={24} color="#60A5FA" />
        ) : (
          <FileText size={24} color="#9CA3AF" />
        )}
      </View>
      <View style={styles.fileInfo}>
        <Text style={styles.fileName}>{item.name}</Text>
        <Text style={styles.fileMeta}>
          {item.size ? `${Math.round(item.size / 1024)} KB` : '—'} • {new Date(item.lastModified).toLocaleDateString()}
        </Text>
      </View>
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Workspace</Text>
        <TouchableOpacity onPress={handleCreateDemoFile} style={styles.addButton}>
          <Plus size={20} color="#3B82F6" />
        </TouchableOpacity>
      </View>

      {files.length === 0 ? (
        <View style={styles.emptyState}>
          <FolderOpen size={48} color="#374151" />
          <Text style={styles.emptyTitle}>No files yet</Text>
          <Text style={styles.emptySubtitle}>
            Files created by Agent47 will appear here.{'\n'}
            Try asking it to create a website or script!
          </Text>
          <TouchableOpacity style={styles.demoButton} onPress={handleCreateDemoFile}>
            <Text style={styles.demoButtonText}>Create Demo File</Text>
          </TouchableOpacity>
        </View>
      ) : (
        <FlatList
          data={files}
          renderItem={renderFile}
          keyExtractor={(item) => item.id}
          contentContainerStyle={styles.list}
        />
      )}
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0A0F1C',
  },
  header: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: 20,
    borderBottomWidth: 1,
    borderBottomColor: '#1F2937',
  },
  title: {
    color: '#F3F4F6',
    fontSize: 22,
    fontWeight: '700',
  },
  addButton: {
    padding: 8,
  },
  list: {
    padding: 16,
  },
  fileItem: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1F2937',
    padding: 16,
    borderRadius: 12,
    marginBottom: 10,
  },
  fileIcon: {
    marginRight: 14,
  },
  fileInfo: {
    flex: 1,
  },
  fileName: {
    color: '#F3F4F6',
    fontSize: 16,
    fontWeight: '600',
  },
  fileMeta: {
    color: '#6B7280',
    fontSize: 13,
    marginTop: 2,
  },
  emptyState: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 40,
  },
  emptyTitle: {
    color: '#9CA3AF',
    fontSize: 20,
    fontWeight: '600',
    marginTop: 16,
  },
  emptySubtitle: {
    color: '#6B7280',
    textAlign: 'center',
    marginTop: 8,
    lineHeight: 22,
  },
  demoButton: {
    marginTop: 24,
    backgroundColor: '#3B82F6',
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderRadius: 999,
  },
  demoButtonText: {
    color: '#fff',
    fontWeight: '600',
  },
});