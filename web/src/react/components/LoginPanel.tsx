import type { Dict, Principal } from "../types";

type Credentials = {
  email: string;
  password: string;
  displayName: string;
  inviteCode: string;
};

type Props = {
  principal: Principal;
  authConfig: Dict;
  credentials: Credentials;
  onPrincipalChange(principal: Principal): void;
  onCredentialsChange(credentials: Credentials): void;
  onLogin(): void;
  onRegister(): void;
};

export function LoginPanel({
  principal,
  authConfig,
  credentials,
  onPrincipalChange,
  onCredentialsChange,
  onLogin,
  onRegister,
}: Props) {
  const update = (key: keyof Credentials, value: string) => {
    onCredentialsChange({ ...credentials, [key]: value });
  };

  return (
    <section className="panel login-panel">
      <div className="panel-heading">
        <div>
          <h2>Access</h2>
          <p className="section-copy">
            Sign in with your Planora account. New users register with an invite code created by a university admin.
          </p>
        </div>
      </div>

      <div className="identity-grid">
        <label>
          Email
          <input
            type="email"
            value={credentials.email}
            onChange={(event) => update("email", event.target.value)}
            placeholder="name@example.edu"
            autoComplete="email"
          />
        </label>
        <label>
          Password
          <input
            type="password"
            value={credentials.password}
            onChange={(event) => update("password", event.target.value)}
            placeholder="At least 10 characters"
            autoComplete="current-password"
          />
        </label>
        <button type="button" onClick={onLogin}>
          Sign in
        </button>
      </div>

      {authConfig.registration_enabled !== false ? (
        <div className="provider-section">
          <div className="provider-heading">
            <strong>Create account</strong>
            <span className="muted">The invite code decides your university group and starting role.</span>
          </div>
          <div className="identity-grid">
            <label>
              Display name
              <input
                value={credentials.displayName}
                onChange={(event) => update("displayName", event.target.value)}
                placeholder="Full name"
                autoComplete="name"
              />
            </label>
            <label>
              Invite code
              <input
                value={credentials.inviteCode}
                onChange={(event) => update("inviteCode", event.target.value)}
                placeholder="Code from your admin"
                autoComplete="off"
              />
            </label>
            <button type="button" onClick={onRegister}>
              Register
            </button>
          </div>
        </div>
      ) : null}

      <div className="auth-help-grid">
        <div className="info-card">
          <strong>Email confirmation</strong>
          <p>
            {authConfig.email_verification_required === false
              ? "Email confirmation is disabled for this deployment."
              : "After registration, open the confirmation link before signing in."}
          </p>
        </div>
        <div className="info-card">
          <strong>Current session</strong>
          <p>
            {principal.user_id ? `${principal.user_id} · ${principal.role} · ${principal.tenant_id}` : "Not signed in yet."}
          </p>
        </div>
      </div>
    </section>
  );
}
