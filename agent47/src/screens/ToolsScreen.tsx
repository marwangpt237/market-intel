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
import { Tool } from '../types';

export const ToolsScreen: React.FC = () => {
  const { availableTools } = useAgentStore();

  const renderTool = ({ item }: { item: Tool }) => (
    <TouchableOpacity style={styles.toolCard}>
      <View style={styles.iconContainer}>
        <Text style={styles.icon}>{item.icon}</Text>
      </View>
      <View style={styles.toolInfo}>
        <Text style={styles.toolName}>{item.name}</Text>
        <Text style={styles.toolDesc}>{item.description}</Text>
        <View style={styles.badge}>
          <Text style={styles.badgeText}>{item.category}</Text>
        </View>
      </View>
      <View style={[styles.statusDot, { backgroundColor: item.available ? '#22C55E' : '#EF4444' }]} />
    </TouchableOpacity>
  );

  return (
    <SafeAreaView style={styles.container}>
      <View style={styles.header}>
        <Text style={styles.title}>Available Tools</Text>
        <Text style={styles.subtitle}>Agent47 can use these capabilities</Text>
      </View>

      <FlatList
        data={availableTools}
        renderItem={renderTool}
        keyExtractor={(item) => item.id}
        contentContainerStyle={styles.list}
      />
    </SafeAreaView>
  );
};

const styles = StyleSheet.create({
  container: {
    flex: 1,
    backgroundColor: '#0A0F1C',
  },
  header: {
    padding: 20,
    paddingBottom: 12,
  },
  title: {
    color: '#F3F4F6',
    fontSize: 24,
    fontWeight: '700',
  },
  subtitle: {
    color: '#6B7280',
    marginTop: 4,
  },
  list: {
    paddingHorizontal: 16,
  },
  toolCard: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#1F2937',
    padding: 16,
    borderRadius: 16,
    marginBottom: 12,
  },
  iconContainer: {
    width: 52,
    height: 52,
    borderRadius: 14,
    backgroundColor: '#374151',
    alignItems: 'center',
    justifyContent: 'center',
    marginRight: 14,
  },
  icon: {
    fontSize: 26,
  },
  toolInfo: {
    flex: 1,
  },
  toolName: {
    color: '#F3F4F6',
    fontSize: 17,
    fontWeight: '600',
  },
  toolDesc: {
    color: '#9CA3AF',
    fontSize: 14,
    marginTop: 3,
  },
  badge: {
    alignSelf: 'flex-start',
    backgroundColor: '#374151',
    paddingHorizontal: 8,
    paddingVertical: 2,
    borderRadius: 999,
    marginTop: 8,
  },
  badgeText: {
    color: '#60A5FA',
    fontSize: 11,
    fontWeight: '500',
    textTransform: 'uppercase',
  },
  statusDot: {
    width: 10,
    height: 10,
    borderRadius: 5,
    marginLeft: 12,
  },
});