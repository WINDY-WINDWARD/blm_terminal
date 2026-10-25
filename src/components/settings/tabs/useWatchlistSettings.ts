'use client';

import { useAtom } from 'jotai';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import {
  watchlistColumnsAtom,
  moversColumnsAtom,
  watchlistsAtom,
  activeWatchlistIdAtom,
  type Watchlist,
} from '@/store/terminalStore';

export function useWatchlistSettings() {
  const qc = useQueryClient();
  const [watchlistCols, setWatchlistCols] = useAtom(watchlistColumnsAtom);
  const [moversCols, setMoversCols] = useAtom(moversColumnsAtom);
  const [watchlists, setWatchlists] = useAtom(watchlistsAtom);
  const [activeWatchlistId, setActiveWatchlistId] = useAtom(activeWatchlistIdAtom);

  useQuery({
    queryKey: ['watchlists'],
    queryFn: async () => {
      const res = await fetch('/api/watchlists');
      if (!res.ok) throw new Error('Failed to fetch watchlists');
      const data = (await res.json()) as Watchlist[];
      setWatchlists(data);
      return data;
    },
    staleTime: 300_000,
  });

  const handleWatchlistChange = (key: string, checked: boolean) => {
    const newCols = checked ? [...watchlistCols, key] : watchlistCols.filter((c) => c !== key);
    setWatchlistCols(newCols);
  };

  const handleMoversChange = (key: string, checked: boolean) => {
    const newCols = checked ? [...moversCols, key] : moversCols.filter((c) => c !== key);
    setMoversCols(newCols);
  };

  const handleDeleteWatchlist = async (id: number, name: string) => {
    if (!confirm(`Delete watchlist "${name}"? All items will be deleted.`)) return;
    try {
      const res = await fetch(`/api/watchlists/${id}`, { method: 'DELETE' });
      if (!res.ok) {
        const data = await res.json();
        alert(data.detail || 'Failed to delete watchlist');
        return;
      }
      const data = await fetch('/api/watchlists').then(r => r.json()) as Watchlist[];
      setWatchlists(data);
      if (activeWatchlistId === id) setActiveWatchlistId(1);
      void qc.invalidateQueries({ queryKey: ['watchlist'] });
    } catch (err) {
      console.error('Failed to delete watchlist:', err);
      alert('Failed to delete watchlist');
    }
  };

  return {
    watchlistCols,
    moversCols,
    watchlists,
    activeWatchlistId,
    handleWatchlistChange,
    handleMoversChange,
    handleDeleteWatchlist,
  };
}
