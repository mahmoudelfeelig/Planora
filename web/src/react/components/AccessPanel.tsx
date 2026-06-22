import { useMemo, useState } from "react";
import type { Dict, Principal } from "../types";

type Props = {
  principal: Principal;
  snapshot: Dict;
  onChange(change: Dict): Promise<void>;
};

const ROLES = ["student", "ta", "professor", "uni_admin", "admin"];

export function AccessPanel({ principal, snapshot, onChange }: Props) {
  const users = (snapshot.users || []) as Dict[];
  const groups = (snapshot.groups || []) as Dict[];
  const memberships = (snapshot.memberships || []) as Dict[];
  const bindings = (snapshot.role_bindings || []) as Dict[];
  const invites = (snapshot.invite_codes || []) as Dict[];
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
  const tenantUsers = useMemo(
    () => users.filter((user) => principal.is_global_admin || String(user.tenant_id) === principal.tenant_id),
    [principal.is_global_admin, principal.tenant_id, users],
  );

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
          <label>
            New group
            <input value={groupName} onChange={(event) => setGroupName(event.target.value)} placeholder="Computer Science staff" />
          </label>
          <button type="button" disabled={!groupName.trim()} onClick={() => {
            void onChange({ action: "create_group", name: groupName.trim(), tenant_id: principal.tenant_id }).then(() => setGroupName(""));
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
          <button type="button" disabled={!selectedUser} onClick={() => void onChange({ action: "set_role", user_id: selectedUser, role: selectedRole, tenant_id: principal.tenant_id })}>
            Assign role
          </button>
          <button type="button" className="danger-button" disabled={!selectedUser || selectedUser === principal.user_id} onClick={() => {
            if (window.confirm("Disable this account? The user will lose access, but audit history and existing records stay intact.")) {
              void onChange({ action: "set_disabled", user_id: selectedUser, disabled: true, tenant_id: principal.tenant_id });
            }
          }}>
            Disable account
          </button>
          <button type="button" className="secondary-button" disabled={!selectedUser} onClick={() => void onChange({ action: "set_disabled", user_id: selectedUser, disabled: false, tenant_id: principal.tenant_id })}>
            Re-enable account
          </button>
          <label>
            Planora group
            <select value={selectedGroup} onChange={(event) => setSelectedGroup(event.target.value)}>
              <option value="">Select group</option>
              {groups.map((group) => <option key={String(group.group_id)} value={String(group.group_id)}>{String(group.name)}</option>)}
            </select>
          </label>
          <button type="button" disabled={!selectedUser || !selectedGroup} onClick={() => void onChange({ action: "set_membership", user_id: selectedUser, group_id: selectedGroup, enabled: true, tenant_id: principal.tenant_id })}>
            Add member
          </button>
          <label>Staff ID<input inputMode="numeric" value={staffId} onChange={(event) => setStaffId(event.target.value)} placeholder="Professor or TA ID" /></label>
          <label>Student group ID<input inputMode="numeric" value={studentGroupId} onChange={(event) => setStudentGroupId(event.target.value)} placeholder="Schedule group ID" /></label>
          <button type="button" disabled={!selectedUser} onClick={() => void onChange({ action: "link_schedule_identity", user_id: selectedUser, staff_id: staffId, student_group_id: studentGroupId, tenant_id: principal.tenant_id })}>Link schedule identity</button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><h2>Scoped group role</h2><p className="section-copy">Grant a Planora group a role for the whole tenant or a specific department, program, course, or student group.</p></div></div>
        <div className="identity-grid access-controls">
          <label>Planora group<select value={selectedGroup} onChange={(event) => setSelectedGroup(event.target.value)}><option value="">Select group</option>{groups.map((group) => <option key={String(group.group_id)} value={String(group.group_id)}>{String(group.name)}</option>)}</select></label>
          <label>Role<select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>{ROLES.filter((role) => role !== "admin" || principal.is_global_admin).map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
          <label>Scope<select value={scopeType} onChange={(event) => setScopeType(event.target.value)}><option value="tenant">Entire tenant</option><option value="department">Department</option><option value="program">Program</option><option value="course">Course</option><option value="group">Student group</option></select></label>
          <label>Scope ID<input value={scopeId} onChange={(event) => setScopeId(event.target.value)} disabled={scopeType === "tenant"} /></label>
          <button type="button" disabled={!selectedGroup} onClick={() => void onChange({ action: "bind_role", principal_type: "group", principal_id: selectedGroup, role: selectedRole, scope_type: scopeType, scope_id: scopeType === "tenant" ? "*" : scopeId, tenant_id: principal.tenant_id })}>Bind group role</button>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading"><div><h2>Invite codes</h2><p className="section-copy">Create a code manually, leave it blank for a random one, or rotate a leaked code. Existing members stay in the group.</p></div></div>
        <div className="identity-grid access-controls">
          <label>Planora group<select value={selectedGroup} onChange={(event) => setSelectedGroup(event.target.value)}><option value="">Select group</option>{groups.map((group) => <option key={String(group.group_id)} value={String(group.group_id)}>{String(group.name)}</option>)}</select></label>
          <label>Invite role<select value={selectedRole} onChange={(event) => setSelectedRole(event.target.value)}>{ROLES.filter((role) => role !== "admin" && (role !== "uni_admin" || principal.is_global_admin || principal.role === "uni_admin")).map((role) => <option key={role} value={role}>{role}</option>)}</select></label>
          <label>Label<input value={inviteLabel} onChange={(event) => setInviteLabel(event.target.value)} placeholder="Fall 2026 CS students" /></label>
          <label>Code<input value={inviteCode} onChange={(event) => setInviteCode(event.target.value)} placeholder="Leave blank for random" autoComplete="off" /></label>
          <button type="button" disabled={!selectedGroup} onClick={() => void onChange({ action: "create_invite", group_id: selectedGroup, role: selectedRole, label: inviteLabel, code: inviteCode, tenant_id: principal.tenant_id })}>Create invite</button>
          <label>Existing invite<select value={selectedInvite} onChange={(event) => setSelectedInvite(event.target.value)}><option value="">Select invite</option>{invites.map((invite) => <option key={String(invite.invite_id)} value={String(invite.invite_id)}>{String(invite.label || invite.invite_id)} · {String(invite.role)}</option>)}</select></label>
          <button type="button" disabled={!selectedInvite} onClick={() => void onChange({ action: "rotate_invite", invite_id: selectedInvite, code: inviteCode, label: inviteLabel || undefined, tenant_id: principal.tenant_id })}>Rotate selected</button>
          <button type="button" disabled={!selectedInvite} onClick={() => void onChange({ action: "set_invite_disabled", invite_id: selectedInvite, disabled: true, tenant_id: principal.tenant_id })}>Disable selected</button>
        </div>
        {snapshot.new_invite_code ? <div className="inline-note">New invite code: <strong>{String(snapshot.new_invite_code)}</strong></div> : null}
      </section>

      <section className="panel">
        <h2>Directory</h2>
        <div className="table-like access-table">
          <div className="table-row header"><span>User</span><span>Role</span><span>Tenant</span><span>Status</span></div>
          {tenantUsers.map((user) => (
            <div className="table-row" key={String(user.user_id)}>
              <span>{String(user.display_name || user.user_id)}</span>
              <span>{String(user.role)}</span>
              <span>{String(user.tenant_id)}</span>
              <span>{Number(user.disabled || 0) ? "disabled" : "active"}</span>
            </div>
          ))}
        </div>
        <p className="muted">{groups.length} groups, {memberships.length} memberships, {bindings.length} scoped bindings, {invites.length} invite codes.</p>
      </section>
    </div>
  );
}
