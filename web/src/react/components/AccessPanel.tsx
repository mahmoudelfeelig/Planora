import { useMemo, useState } from "react";
import type { Dict, Principal } from "../types";

type Props = {
  principal: Principal;
  snapshot: Dict;
  onChange(change: Dict): Promise<void>;
};

const ROLES = ["student", "ta", "professor", "uni_admin", "admin"];

export function AccessPanel({ principal, snapshot, onChange }: Props) {
  const users = useMemo(() => (snapshot.users || []) as Dict[], [snapshot.users]);
  const groups = useMemo(() => (snapshot.groups || []) as Dict[], [snapshot.groups]);
  const memberships = (snapshot.memberships || []) as Dict[];
  const bindings = (snapshot.role_bindings || []) as Dict[];
  const invites = useMemo(() => (snapshot.invite_codes || []) as Dict[], [snapshot.invite_codes]);
  const accountTenants = useMemo(() => (snapshot.account_tenants || []) as Dict[], [snapshot.account_tenants]);
  const [groupName, setGroupName] = useState("");
  const [selectedUser, setSelectedUser] = useState("");
  const [selectedGroup, setSelectedGroup] = useState("");
  const [selectedRole, setSelectedRole] = useState("student");
  const [inviteCode, setInviteCode] = useState("");
  const [inviteLabel, setInviteLabel] = useState("");
  const [selectedInvite, setSelectedInvite] = useState("");
  const [staffId, setStaffId] = useState("");
  const [studentGroupId, setStudentGroupId] = useState("");
  const [scopeType, setScopeType] = useState("tenant");
  const [scopeId, setScopeId] = useState("*");
  const tenantIds = useMemo(
    () => Array.from(new Set([principal.tenant_id, ...users.map((row) => String(row.tenant_id || "")), ...groups.map((row) => String(row.tenant_id || "")), ...accountTenants.map((row) => String(row.tenant_id || ""))].filter(Boolean))).sort(),
    [accountTenants, groups, principal.tenant_id, users],
  );
  const [selectedTenant, setSelectedTenant] = useState(principal.tenant_id);
  const tenantId = principal.is_global_admin && tenantIds.includes(selectedTenant) ? selectedTenant : principal.tenant_id;
  const tenantUsers = useMemo(
    () => accountTenants
      .filter((account) => String(account.tenant_id) === tenantId)
      .map((account): Dict => ({
        ...(users.find((user) => String(user.user_id) === String(account.user_id)) || {}),
        ...account,
      })),
    [accountTenants, tenantId, users],
  );
  const tenantGroups = useMemo(() => groups.filter((group) => String(group.tenant_id) === tenantId), [groups, tenantId]);
  const tenantInvites = useMemo(() => invites.filter((invite) => String(invite.tenant_id) === tenantId), [invites, tenantId]);

  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Access control</h2>
            <p className="section-copy">
              Roles are assigned by the backend. Invite codes place new users into a Planora group without changing current members when a code is rotated.
            </p>
          </div>
        </div>
        <div className="metric-grid role-matrix" aria-label="Role permission summary">
          <div><span>Student</span><strong>View group schedules</strong></div>
          <div><span>TA / Professor</span><strong>View assigned teaching</strong></div>
          <div><span>University admin</span><strong>Solve, repair, import</strong></div>
          <div><span>Global admin</span><strong>All tenants and audit</strong></div>
        </div>
        <div className="identity-grid access-controls">
          {principal.is_global_admin ? (
            <label>
              Organization
              <select value={selectedTenant} onChange={(event) => {
                setSelectedTenant(event.target.value);
                setSelectedUser("");
                setSelectedGroup("");
                setSelectedInvite("");
              }}>
                {tenantIds.map((id) => <option key={id} value={id}>{id}</option>)}
              </select>
            </label>
          ) : null}
          <label>
            New group
            <input value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="Computer Science staff" />
          </label>
          <button type="button" disabled={!groupName.trim()} onClick={() => {
            void onChange({ action: "create_group", name: groupName.trim(), tenant_id: tenantId }).then(() => setGroupName(""));
          }}>
            Create group
          </button>
          <label>
            User
            <select value={selectedUser} onChange={(event) => setSelectedUser(event.target.value)}>
              <option value="">Select user</option>
              {tenantUsers.map((user) => <option key={String(user.user_id)} value={String(user.user_id)}>{String(user.display_name || user.user_id)}</option>)}
            </select>
          </label>
          <label>
            Role
            <select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>
              {ROLES.filter((role) => role !== "admin" || principal.is_global_admin).map((role) => <option key={role} value={role}>{role}</option>)}
            </select>
          </label>
          <button type="button" disabled={!selectedUser} onClick={() => void onChange({ action: "set_role", user_id: selectedUser, role: selectedRole, tenant_id: tenantId })}>
            Assign role
          </button>
          <button type="button" className="danger-button" disabled={!selectedUser || selectedUser === principal.user_id} onClick={() => {
            if (window.confirm("Disable this account? The user will lose access, but audit history and existing records stay intact.")) {
              void onChange({ action: "set_disabled", user_id: selectedUser, disabled: true, tenant_id: tenantId });
            }
          }}>
            Disable account
          </button>
          <button type="button" className="secondary-button" disabled={!selectedUser} onClick={() => void onChange({ action: "set_disabled", user_id: selectedUser, disabled: false, tenant_id: tenantId })}>
            Re-enable account
          </button>
          {principal.is_global_admin ? (
            <button type="button" className="danger-button" disabled={!selectedUser || selectedUser === principal.user_id} onClick={() => {
              if (window.confirm("Permanently delete this account from Planora? Audit rows remain, but login sessions, group memberships, tenant links, and auth tokens will be removed.")) {
                void onChange({ action: "delete_user", user_id: selectedUser, tenant_id: tenantId }).then(() => setSelectedUser(""));
              }
            }}>
              Delete user
            </button>
          ) : null}
          <label>
            Planora group
            <select value={selectedGroup} onChange={(event) => setSelectedGroup(event.target.value)}>
              <option value="">Select group</option>
              {tenantGroups.map((group) => <option key={String(group.group_id)} value={String(group.group_id)}>{String(group.name)}</option>)}
            </select>
          </label>
          <button type="button" disabled={!selectedUser || !selectedGroup} onClick={() => void onChange({ action: "set_membership", user_id: selectedUser, group_id: selectedGroup, enabled: true, tenant_id: tenantId })}>
            Add member
          </button>
          <label>Staff ID<input inputMode="numeric" value={staffId} onChange={(event) => setStaffId(event.target.value)} placeholder="Professor or TA ID" /></label>
          <label>Student group ID<input inputMode="numeric" value={studentGroupId} onChange={(event) => setStudentGroupId(event.target.value)} placeholder="Schedule group ID" /></label>
          <button type="button" disabled={!selectedUser} onClick={() => void onChange({ action: "link_schedule_identity", user_id: selectedUser, staff_id: staffId, student_group_id: studentGroupId, tenant_id: tenantId })}>Link schedule identity</button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><h2>Scoped group role</h2><p className="section-copy">Grant a Planora group a role for the whole tenant or a specific department, program, course, or student group.</p></div></div>
        <div className="identity-grid access-controls">
          <label>Planora group<select value={selectedGroup} onChange={(event) => setSelectedGroup(event.target.value)}><option value="">Select group</option>{tenantGroups.map((group) => <option key={String(group.group_id)} value={String(group.group_id)}>{String(group.name)}</option>)}</select></label>
          <label>Role<select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>{ROLES.filter((role) => role !== "admin" || principal.is_global_admin).map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
          <label>Scope<select value={scopeType} onChange={(event) => setScopeType(event.target.value)}><option value="tenant">Entire tenant</option><option value="department">Department</option><option value="program">Program</option><option value="course">Course</option><option value="group">Student group</option></select></label>
          <label>Scope ID<input value={scopeId} onChange={(event) => setScopeId(event.target.value)} disabled={scopeType === "tenant"} /></label>
          <button type="button" disabled={!selectedGroup} onClick={() => void onChange({ action: "bind_role", principal_type: "group", principal_id: selectedGroup, role: selectedRole, scope_type: scopeType, scope_id: scopeType === "tenant" ? "*" : scopeId, tenant_id: tenantId })}>Bind group role</button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><h2>Invite codes</h2><p className="section-copy">Create a code manually, leave it blank for a random one, or rotate a leaked code. Existing members stay in the group.</p></div></div>
        <div className="identity-grid access-controls">
          <label>Planora group<select value={selectedGroup} onChange={(event) => setSelectedGroup(event.target.value)}><option value="">Select group</option>{tenantGroups.map((group) => <option key={String(group.group_id)} value={String(group.group_id)}>{String(group.name)}</option>)}</select></label>
          <label>Invite role<select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>{ROLES.filter((role) => role !== "admin" && (role !== "uni_admin" || principal.is_global_admin || principal.role === "uni_admin")).map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
          <label>Label<input value={inviteLabel} onChange={(event) => setInviteLabel(event.target.value)} placeholder="Fall 2026 CS students" /></label>
          <label>Code<input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="Leave blank for random" autoComplete="off" /></label>
          <button type="button" disabled={!selectedGroup} onClick={() => void onChange({ action: "create_invite", group_id: selectedGroup, role: selectedRole, label: inviteLabel, code: inviteCode, tenant_id: tenantId })}>Create invite</button>
          <label>Existing invite<select value={selectedInvite} onChange={(event) => setSelectedInvite(event.target.value)}><option value="">Select invite</option>{tenantInvites.map((invite) => <option key={String(invite.invite_id)} value={String(invite.invite_id)}>{String(invite.label || invite.invite_id)} · {String(invite.role)}</option>)}</select></label>
          <button type="button" disabled={!selectedInvite} onClick={() => void onChange({ action: "rotate_invite", invite_id: selectedInvite, code: inviteCode, label: inviteLabel || undefined, tenant_id: tenantId })}>Rotate selected</button>
          <button type="button" disabled={!selectedInvite} onClick={() => void onChange({ action: "set_invite_disabled", invite_id: selectedInvite, disabled: true, tenant_id: tenantId })}>Disable selected</button>
        </div>
        {snapshot.new_invite_code ? <div className="inline-note">New invite code: <strong>{String(snapshot.new_invite_code)}</strong></div> : null}
      </section>

      <section className="panel">
        <h2>Directory</h2>
        <div className="table-like access-table">
          <div className="table-row header"><span>User</span><span>Role</span><span>Tenant</span><span>Status</span><span>Actions</span></div>
          {tenantUsers.map((user) => (
            <div className="table-row" key={String(user.user_id)}>
              <span>{String(user.display_name || user.user_id)}</span>
              <span>{String(user.role)}</span>
              <span>{String(user.tenant_id)}</span>
              <span>{Number(user.disabled || 0) ? "disabled" : "active"}</span>
              <span className="row-actions">
                <button type="button" className="secondary-button" onClick={() => setSelectedUser(String(user.user_id))}>Select</button>
                <button
                  type="button"
                  className="secondary-button"
                  disabled={String(user.user_id) === principal.user_id}
                  onClick={() => void onChange({ action: "set_disabled", user_id: String(user.user_id), disabled: !Number(user.disabled || 0), tenant_id: tenantId })}
                >
                  {Number(user.disabled || 0) ? "Enable" : "Disable"}
                </button>
                {principal.is_global_admin ? (
                  <button
                    type="button"
                    className="danger-button"
                    disabled={String(user.user_id) === principal.user_id}
                    onClick={() => {
                      if (window.confirm(`Permanently delete ${String(user.display_name || user.user_id)}? This cannot be undone.`)) {
                        void onChange({ action: "delete_user", user_id: String(user.user_id), tenant_id: tenantId });
                      }
                    }}
                  >
                    Delete
                  </button>
                ) : null}
              </span>
            </div>
          ))}
        </div>
        <p className="muted">{tenantGroups.length} groups, {memberships.filter((row) => String(row.tenant_id) === tenantId).length} memberships, {bindings.filter((row) => String(row.tenant_id) === tenantId).length} scoped bindings, {tenantInvites.length} invite codes.</p>
      </section>
    </div>
  );
}
