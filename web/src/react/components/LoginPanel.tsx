import { useEffect, useState } from "react";
import type { Dict, Principal } from "../types";

type Credentials = {
  email: string;
  password: string;
  newPassword: string;
  displayName: string;
  inviteCode: string;
  verificationCode: string;
  resetCode: string;
  resetToken: string;
};

type Props = {
  principal: Principal;
  authConfig: Dict;
  credentials: Credentials;
  onCredentialsChange(credentials: Credentials): void;
  onLogin(): void | Promise<void>;
  onRegister(): void | Promise<void>;
  onVerify(): void | Promise<void>;
  onForgotPassword(): void | Promise<void>;
  onResetPassword(): void | Promise<void>;
  verificationSuccess?: boolean;
  redirectSeconds?: number;
  onRedirectNow?: () => void;
  initialMode?: AuthMode;
};

type AuthMode = "login" | "register" | "verify" | "forgot" | "reset";

export function LoginPanel({
  principal,
  authConfig,
  credentials,
  onCredentialsChange,
  onLogin,
  onRegister,
  onVerify,
  onForgotPassword,
  onResetPassword,
  verificationSuccess = false,
  redirectSeconds = 5,
  onRedirectNow,
  initialMode = "login",
}: Props) {
  const [mode, setMode] = useState<AuthMode>(initialMode);
  useEffect(() => setMode(initialMode), [initialMode]);
  const update = (key: keyof Credentials, value: string) => {
    onCredentialsChange({ ...credentials, [key]: value });
  };

  if (verificationSuccess) {
    return (
      <section className="login-card auth-page-card verified-card" aria-live="polite">
        <img className="auth-logo-large" src="/app-icon.png" alt="" />
        <div className="auth-card-heading">
          <h1>Email confirmed</h1>
          <p className="section-copy">
            Your account is active and you are signed in. Redirecting to the home page in {redirectSeconds} second{redirectSeconds === 1 ? "" : "s"}.
          </p>
        </div>
        <button type="button" onClick={onRedirectNow}>Not redirecting? Click here</button>
      </section>
    );
  }

  return (
    <section className="login-card auth-page-card">
      <div className="auth-card-heading">
        <h1>
          {mode === "login"
            ? "Sign in"
            : mode === "register"
              ? "Create account"
              : mode === "verify"
                ? "Confirm email"
                : mode === "forgot"
                  ? "Reset password"
                  : "Choose new password"}
        </h1>
        <p className="section-copy">
          {mode === "login"
            ? "Use your Planora account to open schedules, solver tools, diagnostics, and group workspaces."
            : mode === "register"
              ? "Create your account first. After confirmation, use an invite code from My Groups to join a university group."
              : mode === "verify"
                ? "Enter the six-digit confirmation code from your email. The secure link in the email works too."
                : mode === "forgot"
                  ? "Enter your account email and Planora will send a reset link and one-time code."
                  : "Enter the reset code or use the secure link from your email, then choose a new password."}
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
          <p className="auth-switch">
            Forgot your password? <button type="button" onClick={() => setMode("forgot")}>Reset it</button>
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
            Confirmation code
            <input
              value={credentials.verificationCode}
              onChange={(event) => update("verificationCode", event.target.value)}
              placeholder="123456"
              autoComplete="one-time-code"
              inputMode="numeric"
            />
          </label>
          <button type="button" onClick={onVerify}>Confirm email</button>
          <p className="auth-switch">
            Confirmed already? <button type="button" onClick={() => setMode("login")}>Sign in</button>
          </p>
        </div>
      ) : null}

      {mode === "forgot" ? (
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
          <button
            type="button"
            onClick={async () => {
              await onForgotPassword();
              setMode("reset");
            }}
          >
            Send reset email
          </button>
          <p className="auth-switch">
            Remembered it? <button type="button" onClick={() => setMode("login")}>Sign in</button>
          </p>
        </div>
      ) : null}

      {mode === "reset" ? (
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
            Reset code
            <input
              value={credentials.resetCode || credentials.resetToken}
              onChange={(event) => {
                update(credentials.resetToken ? "resetToken" : "resetCode", event.target.value);
              }}
              placeholder="123456"
              autoComplete="one-time-code"
            />
          </label>
          <label>
            New password
            <input
              type="password"
              value={credentials.newPassword}
              onChange={(event) => update("newPassword", event.target.value)}
              placeholder="At least 10 characters"
              autoComplete="new-password"
            />
          </label>
          <button type="button" onClick={onResetPassword}>Reset password</button>
          <p className="auth-switch">
            Back to <button type="button" onClick={() => setMode("login")}>sign in</button>
          </p>
        </div>
      ) : null}

    </section>
  );
}
