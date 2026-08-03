/**
 * Re-export the centralized hook from SavedLayoutsSyncProvider.
 * This maintains backward compatibility while allowing the provider to own
 * the actual implementation.
 *
 * The actual provider implementation is in src/components/SavedLayoutsSyncProvider.tsx
 */
export { useSavedLayoutsSync } from '@/components/SavedLayoutsSyncProvider';
