import type { WidgetTourDefinition } from '../types';

export const adminTour: WidgetTourDefinition = {
  command: 'ADMIN',
  title: 'User Management',
  steps: [
    {
      id: 'admin-header',
      anchor: 'admin-header',
      title: 'User Management Header',
      body: 'Overview of administrative controls and role verification. Only users with administrator privileges can view and manage user accounts.',
    },
    {
      id: 'admin-create',
      anchor: 'admin-create',
      title: 'Create New User',
      body: 'Create credentials with username and password, and optionally grant administrator privileges before submitting the form.',
    },
    {
      id: 'admin-users',
      anchor: 'admin-users',
      title: 'Existing Users Directory',
      body: 'Review registered users and their roles, reset passwords with the inline input, or delete users when permitted.',
    },
  ],
};
