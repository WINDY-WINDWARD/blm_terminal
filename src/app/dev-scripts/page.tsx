/**
 * BLM Script Lab v1 — dev-only visual fixtures.
 * Renders 7 fixture scripts (one per output kind + fundamentals + error)
 * executed against the seeded 120-bar fixture. DEV ONLY: 404s in production.
 */
import { notFound } from 'next/navigation';
import FixturesView from './FixturesView';

export default function DevScriptsPage() {
  if (process.env.NODE_ENV === 'production') notFound();
  return <FixturesView />;
}
