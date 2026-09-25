import { Fragment } from 'react'
import { Link, useMatches } from 'react-router'

import {
  Breadcrumb,
  BreadcrumbItem,
  BreadcrumbLink,
  BreadcrumbList,
  BreadcrumbPage,
  BreadcrumbSeparator,
} from '@/components/ui/breadcrumb'

export interface RouteHandle {
  crumb?: string
}

function hasCrumb(handle: unknown): handle is RouteHandle {
  return (
    typeof handle === 'object' &&
    handle !== null &&
    typeof (handle as RouteHandle).crumb === 'string'
  )
}

/** Derived from each matched route's `handle.crumb`, so pages stay declarative. */
export function Breadcrumbs() {
  const matches = useMatches()
  const crumbs = matches
    .filter((match) => hasCrumb(match.handle))
    .map((match) => ({
      id: match.id,
      to: match.pathname,
      label: (match.handle as RouteHandle).crumb!,
    }))

  if (crumbs.length === 0) return null

  return (
    <Breadcrumb>
      <BreadcrumbList>
        {crumbs.map((crumb, index) => {
          const isLast = index === crumbs.length - 1
          return (
            <Fragment key={crumb.id}>
              <BreadcrumbItem className={isLast ? undefined : 'hidden sm:block'}>
                {isLast ? (
                  <BreadcrumbPage>{crumb.label}</BreadcrumbPage>
                ) : (
                  <BreadcrumbLink asChild>
                    <Link to={crumb.to}>{crumb.label}</Link>
                  </BreadcrumbLink>
                )}
              </BreadcrumbItem>
              {isLast ? null : <BreadcrumbSeparator className="hidden sm:block" />}
            </Fragment>
          )
        })}
      </BreadcrumbList>
    </Breadcrumb>
  )
}
