import { useState } from "react";
import type { OrganizationMembership, Principal } from "../types";

type Props = {
  principal: Principal;
  organizations: OrganizationMembership[];
  onJoinInvite(code: string): Promise<void>;
  onSwitchOrganization(tenantId: string): Promise<void>;
};

export function AccountPanel({ principal, organizations, onJoinInvite, onSwitchOrganization }: Props) {
  const [code, setCode] = useState("");
  const groups = principal.groups || [];

  return (
    <div className="account-layout">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>My Account</h2>
            <p className="section-copy">
              Your account can belong to multiple universities and groups. Switch the active organization to change which schedules, courses, and admin tools you can access.
            </p>
          </div>
        </div>
        <div className="profile-grid">
          <div><span>Email/User</span><strong>{principal.user_id}</strong></div>
          <div><span>Organization</span><strong>{principal.tenant_id}</strong></div>
          <div><span>Role</span><strong>{principal.role}</strong></div>
          <div><span>Groups</span><strong>{groups.length}</strong></div>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Organizations</h2>
            <p className="section-copy">
              Each organization is isolated. Your role and groups can be different in each one.
            </p>
          </div>
        </div>
        <div className="org-list">
          {organizations.length ? organizations.map((organization) => (
            <div key={organization.tenant_id} className={organization.active ? "org-row active" : "org-row"}>
              <div>
                <strong>{organization.display_name || organization.tenant_id}</strong>
                <span>{organization.tenant_id} · {organization.role} · {organization.group_count} groups</span>
              </div>
              <button
                type="button"
                className="secondary-button"
                disabled={organization.active}
                onClick={() => void onSwitchOrganization(organization.tenant_id)}
              >
                {organization.active ? "Active" : "Switch"}
              </button>
            </div>
          )) : <p className="muted">No organizations are linked to this account yet.</p>}
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Join Another Group</h2>
            <p className="section-copy">
              Paste an invite code from a university admin. The invite can add you to a different organization without removing any current memberships.
            </p>
          </div>
        </div>
        <div className="join-card">
          <label>
            Invite code
            <input value={code} onChange={(event) => setCode(event.target.value)} placeholder="invite_..." autoComplete="off" />
          </label>
          <button
            type="button"
            disabled={code.trim().length < 8}
            onClick={() => void onJoinInvite(code.trim()).then(() => setCode(""))}
          >
            Join group
          </button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Current Groups</h2>
            <p className="section-copy">Admins can rename groups and grant scoped roles from Users & Invites.</p>
          </div>
        </div>
        <div className="group-list">
          {groups.length ? groups.map((group) => <span key={group}>{group}</span>) : <p className="muted">No groups are attached to this session yet.</p>}
        </div>
      </section>
    </div>
  );
}
