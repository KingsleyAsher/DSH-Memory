import { UPDATE_SOURCES } from './updates.js';

// Local metadata stays available even when every update source is offline.
export function pluginDetails(info) {
  return {
    name: 'DSH 记忆', package: info.name, version: info.version,
    description: '保存和管理全局记忆、项目记忆，供不同 Agent 预设按范围共享。',
    repositories: UPDATE_SOURCES.map(({ id, name, repository }) => ({ id, name, url: repository })),
    issues: 'https://github.com/KingsleyAsher/DSH-Memory/issues',
    updateMode: 'automatic',
  };
}
