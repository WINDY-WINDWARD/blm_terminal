'use client';

import React, { useState, useEffect } from 'react';
import { useAtom } from 'jotai';
import { authAtom } from '@/store/terminalStore';

interface User {
  id: number;
  username: string;
  is_admin: boolean;
}

type PasswordState = Record<number, string>;

export function AdminWidget() {
  const [auth] = useAtom(authAtom);
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  
  const [newUsername, setNewUsername] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newIsAdmin, setNewIsAdmin] = useState(false);
  const [creating, setCreating] = useState(false);
  const [passwordChanges, setPasswordChanges] = useState<PasswordState>({});
  const [changingPassword, setChangingPassword] = useState<number | null>(null);

  useEffect(() => {
    fetchUsers();
  }, []);

  const fetchUsers = async () => {
    try {
      setLoading(true);
      const res = await fetch('/api/py/users');
      if (!res.ok) throw new Error('Failed to fetch users');
      const data = await res.json();
      setUsers(data);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error fetching users');
    } finally {
      setLoading(false);
    }
  };

  const handleCreateUser = async (e: React.FormEvent) => {
    e.preventDefault();
    setError('');
    setCreating(true);

    try {
      const res = await fetch('/api/py/users', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          username: newUsername,
          password: newPassword,
          is_admin: newIsAdmin
        })
      });

      if (!res.ok) {
        const data = await res.json();
        const message = typeof data.detail === 'string'
          ? data.detail
          : Array.isArray(data.detail)
            ? data.detail.map((e: { msg: string }) => e.msg).join('; ')
            : 'Failed to create user';
        throw new Error(message);
      }

      setNewUsername('');
      setNewPassword('');
      setNewIsAdmin(false);
      await fetchUsers();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error creating user');
    } finally {
      setCreating(false);
    }
  };

  const handleDeleteUser = async (userId: number) => {
    if (!confirm('Are you sure you want to delete this user?')) return;
    
    try {
      const res = await fetch(`/api/py/users/${userId}`, {
        method: 'DELETE'
      });
      
      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.detail || 'Failed to delete user');
      }
      
      await fetchUsers();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Error deleting user');
      alert(err instanceof Error ? err.message : 'Error deleting user');
    }
  };

  const handleChangePassword = async (userId: number) => {
    const newPw = passwordChanges[userId];
    if (!newPw || newPw.length < 8) {
      alert('Password must be at least 8 characters');
      return;
    }
    setChangingPassword(userId);
    try {
      const res = await fetch(`/api/py/users/${userId}/password`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ password: newPw }),
      });
      if (!res.ok) {
        const data = await res.json();
        const message = typeof data.detail === 'string'
          ? data.detail
          : 'Failed to change password';
        throw new Error(message);
      }
      setPasswordChanges(prev => ({ ...prev, [userId]: '' }));
    } catch (err: unknown) {
      alert(err instanceof Error ? err.message : 'Error changing password');
    } finally {
      setChangingPassword(null);
    }
  };

  if (!auth?.user?.is_admin) {
    return (
      <div className="h-full w-full flex items-center justify-center bg-terminal-bg text-terminal-red font-mono p-4 text-center">
        ACCESS DENIED: ADMIN ONLY
      </div>
    );
  }

  return (
    <div className="flex flex-col h-full bg-terminal-bg text-terminal-amber font-mono overflow-hidden">
      <div className="p-2 border-b border-terminal-gray">
        <h2 className="text-sm font-bold uppercase tracking-wider">User Management</h2>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-6">
        {error && (
          <div className="p-2 bg-red-900/50 border border-red-500 text-red-200 text-xs">
            {error}
          </div>
        )}

        {/* Create User Form */}
        <div className="bg-terminal-panel p-4 border border-terminal-gray/30">
          <h3 className="text-xs text-terminal-muted mb-4 uppercase">Create New User</h3>
          <form onSubmit={handleCreateUser} className="space-y-3">
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase text-terminal-muted">Username</label>
              <input
                type="text"
                value={newUsername}
                onChange={e => setNewUsername(e.target.value)}
                required
                className="bg-black border border-terminal-gray p-1.5 text-xs text-white focus:border-terminal-amber outline-none"
              />
            </div>
            <div className="flex flex-col gap-1">
              <label className="text-[10px] uppercase text-terminal-muted">Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={e => setNewPassword(e.target.value)}
                required
                className="bg-black border border-terminal-gray p-1.5 text-xs text-white focus:border-terminal-amber outline-none"
              />
            </div>
            <div className="flex items-center gap-2">
              <input
                type="checkbox"
                id="is_admin"
                checked={newIsAdmin}
                onChange={e => setNewIsAdmin(e.target.checked)}
                className="accent-terminal-amber bg-black"
              />
              <label htmlFor="is_admin" className="text-xs uppercase text-terminal-muted select-none cursor-pointer">
                Administrator
              </label>
            </div>
            <button
              type="submit"
              disabled={creating}
              className="mt-2 w-full bg-terminal-gray/20 hover:bg-terminal-amber hover:text-terminal-bg border border-terminal-gray text-xs py-1.5 transition-colors disabled:opacity-50"
            >
              {creating ? 'CREATING...' : 'CREATE USER'}
            </button>
          </form>
        </div>

        {/* User List */}
        <div>
          <h3 className="text-xs text-terminal-muted mb-2 uppercase">Existing Users</h3>
          {loading ? (
            <div className="text-xs text-terminal-muted">Loading...</div>
          ) : (
            <div className="border border-terminal-gray/30 rounded overflow-hidden">
              <table className="w-full text-xs">
                <thead className="bg-terminal-panel text-left">
                  <tr className="border-b border-terminal-gray/30 text-[10px] text-terminal-muted uppercase">
                    <th className="p-2">ID</th>
                    <th className="p-2">Username</th>
                    <th className="p-2">Role</th>
                    <th className="p-2 text-right">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-terminal-gray/20">
                  {users.map(u => (
                    <tr key={u.id} className="hover:bg-white/5">
                      <td className="p-2 text-terminal-muted">{u.id}</td>
                      <td className="p-2 text-white font-bold">{u.username}</td>
                      <td className="p-2">
                        {u.is_admin ? (
                          <span className="text-terminal-amber text-[10px] px-1.5 py-0.5 bg-terminal-amber/10 border border-terminal-amber/30">
                            ADMIN
                          </span>
                        ) : (
                          <span className="text-terminal-muted text-[10px] px-1.5 py-0.5 bg-terminal-gray/20 border border-terminal-gray/30">
                            USER
                          </span>
                        )}
                      </td>
                      <td className="p-2 text-right">
                        <div className="flex items-center gap-1 justify-end">
                          <input
                            type="password"
                            placeholder="New pw"
                            value={passwordChanges[u.id] ?? ''}
                            onChange={e => setPasswordChanges(prev => ({ ...prev, [u.id]: e.target.value }))}
                            className="w-20 bg-black border border-terminal-gray px-1 py-0.5 text-[10px] text-white outline-none focus:border-terminal-amber placeholder:text-terminal-muted/40"
                          />
                          <button
                            onClick={() => handleChangePassword(u.id)}
                            disabled={changingPassword === u.id || !passwordChanges[u.id]}
                            className="text-[10px] text-terminal-amber hover:bg-terminal-amber/10 px-1.5 py-0.5 border border-terminal-gray/40 hover:border-terminal-amber transition-colors disabled:opacity-30"
                          >
                            {changingPassword === u.id ? '...' : 'PW'}
                          </button>
                          {u.id !== auth?.user?.id && (
                            <button
                              onClick={() => handleDeleteUser(u.id)}
                              className="text-terminal-red hover:bg-terminal-red/10 px-1.5 py-0.5 transition-colors"
                            >
                              DEL
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))}
                  {users.length === 0 && (
                    <tr>
                      <td colSpan={4} className="p-4 text-center text-terminal-muted">
                        No users found
                      </td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
