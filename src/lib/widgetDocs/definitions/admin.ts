import type { DocField, WidgetDoc } from '../types';

export const adminDoc: WidgetDoc = {
  command: 'ADMIN',
  title: 'User Management',
  summary:
    'User administration deck for managing credentials, granting administrator roles, and auditing registered accounts.',
  kind: 'panel',
  order: 190,
  screenshot: {
    src: '/docs/widgets/ADMIN.png',
    alt: 'Admin widget screenshot',
    caption: 'Admin as shown in the terminal.',
  },
  sections: [
    {
      heading: 'What this widget shows',
      body: 'A centralized administrative deck for managing terminal user accounts and permission roles. Non-administrative users receive an ACCESS DENIED: ADMIN ONLY lockout screen. Authorized administrators can view all registered users, create new credentials, update passwords, and delete accounts.',
    },
    {
      heading: 'Controls',
      items: [
        'Username input: enter the login username for the new user account.',
        'Password input: enter the initial password for the new user account.',
        'Administrator checkbox: toggle administrative privileges for the new account.',
        'CREATE USER button: submit the form to create the user account via the backend.',
        'New pw input: enter a replacement password with at least 8 characters for an existing user.',
        'PW button: submit the password update request for the selected user record.',
        'DEL button: delete the selected user account after confirming the prompt. Hidden for the current active administrator.',
      ],
    },
    {
      heading: 'Fields and how to read them',
      items: [
        {
          name: 'ID',
          desc: 'Unique numeric identifier assigned to the user account in the database.',
        },
        {
          name: 'USERNAME',
          desc: 'Login identifier associated with the user account.',
        },
        {
          name: 'ROLE',
          desc: 'Account permission level. ADMIN displays in amber for administrator privileges. USER displays in grey for standard accounts.',
        },
        {
          name: 'NEW PW / PW',
          desc: 'Inline password reset input field and submission button for updating user credentials.',
        },
        {
          name: 'DEL',
          desc: 'Deletion action button that prompts for confirmation before removing the user record. This action is disabled on the active user session.',
        },
      ] as DocField[],
    },
    {
      heading: 'Data freshness and limits',
      body: 'User account lists load on mount from /api/py/users and refresh immediately after user creation, password modification, or account deletion. Only authenticated administrators can access user management endpoints. Non-administrators are blocked with an ACCESS DENIED screen.',
    },
    {
      heading: 'Guided tour',
      body: 'The guided tour covers 3 key areas: 1) User Management Header, 2) Create New User, and 3) Existing Users Directory. To replay the tour, open DOCS in another panel, keep this ADMIN panel open, then click REPLAY TOUR.',
    },
  ],
};
