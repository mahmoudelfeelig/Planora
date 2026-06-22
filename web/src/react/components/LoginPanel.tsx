import { useState } from "react";
import type { Dict, Principal } from "../types";

type Credentials = {
  email: string;
  password: string;
  displayName: string;
  inviteCode: string;
  verificationCode: string;
};

type Props = {
  principal: Principal;
  authConfig: Dict;
  credentials: Credentials;
  onCredentialsChange(credentials: Credentials): void;
  onLogin(): void | Promise<void>;
  onRegister(): void | Promise<void>;
  onVerify(): void | Promise<void>;
};

type AuthMode = "login" | "register" | "verify";

export function LoginPanel({
  principal,
  authConfig,
  credentials,
  onCredentialsChange,
  onLogin,
  onRegister,
  onVerify,
}: Props) {
  const [mode, setMode] = useState<AuthMode>("login");
  const update = (key: keyof Credentials, value: string) => {
    onCredentialsChange({ ...credentials, [key]: value });
  };

  return (
    <section className="login-card auth-page-card">
      <div className="auth-card-heading">
        <h1>{mode === "login" ? "Sign in" : mode === "register" ? "Create account" : "Confirm email"}</h1>
        <p className="section-copy">
          {mode === "login"
            ? "Use your Planora account to open schedules, solver tools, diagnostics, and group workspaces."
            : mode === "register"
              ? "Create your account first. After confirmation, use an invite code from My Groups to join a university group."
              : "Paste the confirmation code from your email, then sign in."}
        </p>
      </div>

      {mode === "login" ? (
        <div className="auth-section">
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
              placeholder="Your password"
              autoComplete="current-password"
            />
          </label>
          <button type="button" onClick={onLogin}>Sign in</button>
          <p className="auth-switch">
            No account yet? <button type="button" onClick={() => setMode("register")}>Register</button>
          </p>
        </div>
      ) : null}

      {mode === "register" ? (
        <div className="auth-section">
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
              autoComplete="new-password"
            />
          </label>
          <label>
            Display name
            <input
              value={credentials.displayName}
              onChange={(event) => update("displayName", event.target.value)}
              placeholder="Full name"
              autoComplete="name"
            />
          </label>
          <button
            type="button"
            onClick={async () => {
              await onRegister();
              setMode("verify");
            }}
          >
            Create account
          </button>
          <p className="auth-switch">
            Already have an account? <button type="button" onClick={() => setMode("login")}>Sign in</button>
          </p>
        </div>
      ) : null}

      {mode === "verify" ? (
        <div className="auth-section">
          <label>
            Confirmation code
            <input
              value={credentials.verificationCode}
              onChange={(event) => update("verificationCode", event.target.value)}
              placeholder="verify_..."
              autoComplete="one-time-code"
            />
          </label>
          <button type="button" onClick={onVerify}>Confirm email</button>
          <p className="auth-switch">
            Confirmed already? <button type="button" onClick={() => setMode("login")}>Sign in</button>
          </p>
        </div>
      ) : null}

    </section>
  );
}
