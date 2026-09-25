import { LogOut } from 'lucide-react'
import { Link } from 'react-router'

import { useAuth } from '@/auth/use-auth'
import { PageHeader } from '@/components/feedback/PageHeader'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@/components/ui/card'
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@/components/ui/table'
import { EmptyState } from '@/components/feedback/EmptyState'
import { useDocumentTitle } from '@/hooks/use-document-title'
import { formatDate } from '@/lib/format'
import { ROLE_LABELS } from '@/org/permissions'

export function AccountPage() {
  useDocumentTitle('Account')
  const { user, memberships, logout } = useAuth()

  return (
    <>
      <PageHeader
        title="Account"
        description="Your profile and the organizations you belong to."
        actions={
          <Button variant="outline" onClick={() => logout('user')}>
            <LogOut aria-hidden="true" />
            Sign out
          </Button>
        }
      />

      <Card>
        <CardHeader>
          <CardTitle>Profile</CardTitle>
          <CardDescription>
            Editing your profile is not available in this API yet.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <dl className="grid gap-4 sm:grid-cols-3">
            <div>
              <dt className="text-xs text-muted-foreground">Email</dt>
              <dd className="truncate text-sm">{user?.email ?? '—'}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Display name</dt>
              <dd className="truncate text-sm">{user?.displayName || '—'}</dd>
            </div>
            <div>
              <dt className="text-xs text-muted-foreground">Member since</dt>
              <dd className="text-sm">{formatDate(user?.createdAtUtc)}</dd>
            </div>
          </dl>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Organizations</CardTitle>
        </CardHeader>
        <CardContent>
          {memberships.length === 0 ? (
            <EmptyState
              title="You're not in any organization"
              description="Create one to get started."
              action={
                <Button asChild>
                  <Link to="/orgs">Go to organizations</Link>
                </Button>
              }
            />
          ) : (
            <div className="rounded-lg border">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Organization</TableHead>
                    <TableHead>Role</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {memberships.map((membership) => (
                    <TableRow key={membership.organizationId}>
                      <TableCell>
                        <Link
                          to={`/orgs/${membership.organizationId}`}
                          className="font-medium underline-offset-4 hover:underline"
                        >
                          {membership.organizationName}
                        </Link>
                      </TableCell>
                      <TableCell>
                        <Badge variant="secondary">{ROLE_LABELS[membership.role]}</Badge>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>
    </>
  )
}
