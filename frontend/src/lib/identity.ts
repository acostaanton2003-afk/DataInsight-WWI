import {object, text} from './api';
export type Role = 'ADMIN' | 'ANALYST' | 'VIEWER';
export type Permission = 'profile:read' | 'general:read' | 'customers:read' | 'predictions:read' | 'assistant:use' | 'roles:manage';
export interface Identity {user_id: string; role: Role; permissions: Permission[]}
const permissions: Permission[] = ['profile:read','general:read','customers:read','predictions:read','assistant:use','roles:manage'];
export function parseIdentity(value: unknown): Identity {
  const row = object(value);
  const role = text(row.role);
  const user_id = text(row.user_id);
  if (!['ADMIN','ANALYST','VIEWER'].includes(role) || !/^[0-9a-f]{8}(-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(user_id) ||
      !Array.isArray(row.permissions) || !row.permissions.every(item => permissions.includes(item)) ||
      !row.permissions.includes('profile:read') || new Set(row.permissions).size !== row.permissions.length) {
    throw new Error('Identidad de API no válida.');
  }
  return {user_id, role:role as Role, permissions:row.permissions as Permission[]};
}
