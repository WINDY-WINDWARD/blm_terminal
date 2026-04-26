import { setupServer } from 'msw/node';

// Import all handlers
import { handlers } from './msw-handlers';

export const server = setupServer(...handlers);