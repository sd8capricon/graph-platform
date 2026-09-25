import { Building2, Database, Settings, SlidersHorizontal, Users } from 'lucide-react'
import { NavLink, useParams } from 'react-router'

import { Brand } from '@/components/layout/Brand'
import { OrgSwitcher } from '@/components/layout/OrgSwitcher'
import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from '@/components/ui/sidebar'
import { useCurrentOrg } from '@/org/use-current-org'

interface NavEntry {
  to: string
  label: string
  icon: typeof Database
  /** End-matching, so the overview link is not active on every child route. */
  end?: boolean
  visible?: boolean
}

export function AppSidebar() {
  const { organizationId } = useParams<{ organizationId: string }>()
  const { canGovern } = useCurrentOrg()
  const { setOpenMobile, isMobile } = useSidebar()

  const orgEntries: NavEntry[] = organizationId
    ? [
        {
          to: `/orgs/${organizationId}`,
          label: 'Overview',
          icon: Building2,
          end: true,
        },
        {
          to: `/orgs/${organizationId}/knowledge-bases`,
          label: 'Knowledge bases',
          icon: Database,
        },
        {
          to: `/orgs/${organizationId}/models`,
          label: 'Models',
          icon: SlidersHorizontal,
        },
        // Settings is hidden rather than disabled: a non-admin can never use it.
        {
          to: `/orgs/${organizationId}/settings`,
          label: 'Settings',
          icon: Settings,
          visible: canGovern,
        },
        {
          to: `/orgs/${organizationId}/settings/members`,
          label: 'Members',
          icon: Users,
          visible: canGovern,
        },
      ]
    : []

  const closeOnMobile = () => {
    if (isMobile) setOpenMobile(false)
  }

  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <div className="flex items-center gap-2 px-2 py-1 group-data-[collapsible=icon]:px-0">
          <Brand className="group-data-[collapsible=icon]:hidden" />
        </div>
        <div className="group-data-[collapsible=icon]:hidden">
          <OrgSwitcher currentOrganizationId={organizationId} />
        </div>
      </SidebarHeader>

      <SidebarContent>
        {orgEntries.length > 0 ? (
          <SidebarGroup>
            <SidebarGroupLabel>Organization</SidebarGroupLabel>
            <SidebarGroupContent>
              <SidebarMenu>
                {orgEntries
                  .filter((entry) => entry.visible !== false)
                  .map((entry) => (
                    <SidebarMenuItem key={entry.to}>
                      <NavLink to={entry.to} end={entry.end} onClick={closeOnMobile}>
                        {({ isActive }) => (
                          <SidebarMenuButton asChild isActive={isActive} tooltip={entry.label}>
                            <span>
                              <entry.icon aria-hidden="true" />
                              <span>{entry.label}</span>
                            </span>
                          </SidebarMenuButton>
                        )}
                      </NavLink>
                    </SidebarMenuItem>
                  ))}
              </SidebarMenu>
            </SidebarGroupContent>
          </SidebarGroup>
        ) : null}

        <SidebarGroup>
          <SidebarGroupLabel>Workspace</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              <SidebarMenuItem>
                <NavLink to="/orgs" end onClick={closeOnMobile}>
                  {({ isActive }) => (
                    <SidebarMenuButton asChild isActive={isActive} tooltip="Organizations">
                      <span>
                        <Building2 aria-hidden="true" />
                        <span>Organizations</span>
                      </span>
                    </SidebarMenuButton>
                  )}
                </NavLink>
              </SidebarMenuItem>
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter />
    </Sidebar>
  )
}
