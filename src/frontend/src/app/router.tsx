import { createBrowserRouter } from 'react-router'

import { AuthBoundary } from '@/app/AuthBoundary'
import { ProtectedRoute } from '@/auth/ProtectedRoute'
import { PublicOnlyRoute } from '@/auth/PublicOnlyRoute'
import { RouteErrorBoundary } from '@/components/feedback/RouteErrorBoundary'
import { AppShell } from '@/components/layout/AppShell'
import { OrgGuard } from '@/org/OrgGuard'
import { HomeRedirect } from '@/routes/HomeRedirect'

/**
 * Pages are code-split with React Router's own route-level `lazy`, rather than
 * `React.lazy` consts.
 *
 * Two reasons: the router treats the import as part of the navigation lifecycle,
 * so the current page stays on screen instead of blanking behind a Suspense
 * boundary; and it keeps this module free of component declarations, which is
 * what `react-refresh/only-export-components` requires of a file whose only
 * export is the router itself.
 */
export const router = createBrowserRouter([
  {
    element: <AuthBoundary />,
    errorElement: <RouteErrorBoundary />,
    children: [
      {
        element: <PublicOnlyRoute />,
        children: [
          {
            path: '/login',
            lazy: async () => ({
              Component: (await import('@/routes/LoginPage')).LoginPage,
            }),
          },
          {
            path: '/signup',
            lazy: async () => ({
              Component: (await import('@/routes/SignupPage')).SignupPage,
            }),
          },
        ],
      },
      {
        element: <ProtectedRoute />,
        errorElement: <RouteErrorBoundary />,
        children: [
          {
            element: <AppShell />,
            errorElement: <RouteErrorBoundary />,
            children: [
              { index: true, element: <HomeRedirect /> },
              {
                path: 'orgs',
                handle: { crumb: 'Organizations' },
                children: [
                  {
                    index: true,
                    lazy: async () => ({
                      Component: (await import('@/routes/OrganizationsPage'))
                        .OrganizationsPage,
                    }),
                  },
                  {
                    path: ':organizationId',
                    element: <OrgGuard />,
                    handle: { crumb: 'Organization' },
                    children: [
                      {
                        index: true,
                        lazy: async () => ({
                          Component: (await import('@/routes/OrgOverviewPage'))
                            .OrgOverviewPage,
                        }),
                      },
                      {
                        path: 'knowledge-bases',
                        handle: { crumb: 'Knowledge bases' },
                        children: [
                          {
                            index: true,
                            lazy: async () => ({
                              Component: (await import('@/routes/KnowledgeBasesPage'))
                                .KnowledgeBasesPage,
                            }),
                          },
                          {
                            path: ':knowledgeBaseId',
                            handle: { crumb: 'Detail' },
                            lazy: async () => ({
                              Component: (
                                await import('@/routes/KnowledgeBaseDetailPage')
                              ).KnowledgeBaseDetailPage,
                            }),
                          },
                        ],
                      },
                      {
                        path: 'models',
                        handle: { crumb: 'Models' },
                        children: [
                          {
                            index: true,
                            lazy: async () => ({
                              Component: (await import('@/routes/ModelsPage')).ModelsPage,
                            }),
                          },
                          {
                            path: 'new',
                            handle: { crumb: 'New' },
                            lazy: async () => ({
                              Component: (await import('@/routes/ModelCreatePage'))
                                .ModelCreatePage,
                            }),
                          },
                          {
                            path: ':modelId',
                            handle: { crumb: 'Detail' },
                            lazy: async () => ({
                              Component: (await import('@/routes/ModelDetailPage'))
                                .ModelDetailPage,
                            }),
                          },
                        ],
                      },
                      {
                        path: 'settings',
                        handle: { crumb: 'Settings' },
                        children: [
                          {
                            index: true,
                            lazy: async () => ({
                              Component: (await import('@/routes/OrgSettingsPage'))
                                .OrgSettingsPage,
                            }),
                          },
                          {
                            path: 'members',
                            handle: { crumb: 'Members' },
                            lazy: async () => ({
                              Component: (await import('@/routes/MembersPage')).MembersPage,
                            }),
                          },
                        ],
                      },
                    ],
                  },
                ],
              },
              {
                path: 'account',
                handle: { crumb: 'Account' },
                lazy: async () => ({
                  Component: (await import('@/routes/AccountPage')).AccountPage,
                }),
              },
            ],
          },
        ],
      },
      {
        path: '*',
        lazy: async () => ({
          Component: (await import('@/routes/NotFoundPage')).NotFoundPage,
        }),
      },
    ],
  },
])
