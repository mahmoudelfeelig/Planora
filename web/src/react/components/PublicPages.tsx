import { useState } from "react";
import {
  ArrowRight,
  CheckCircle,
  FileArrowUp,
  MagicWand,
  ShieldCheck,
  UsersThree,
  WarningDiamond,
} from "@phosphor-icons/react";

export function HomeContent() {
  const [previewImproved, setPreviewImproved] = useState(false);
  const previewClasses = [
    { id: "algorithms", label: "Algorithms", detail: "R201 · Dr. Smith", tone: 0, column: 1, initialRow: 1, improvedRow: 1 },
    { id: "data", label: "Data Structures", detail: "R301 · Dr. Lee", tone: 5, column: 2, initialRow: 1, improvedRow: 1 },
    { id: "databases", label: "Databases", detail: "R101 · Dr. Patel", tone: 1, column: 3, initialRow: 1, improvedRow: 1 },
    { id: "math", label: "Discrete Math", detail: "R102 · Dr. Kim", tone: 3, column: 3, initialRow: 2, improvedRow: 2 },
    { id: "systems", label: "Operating Systems", detail: "R202 · Dr. Noor", tone: 4, column: 2, initialRow: 2, improvedRow: 3 },
    { id: "networks", label: "Networks", detail: "R103 · Dr. Johnson", tone: 2, column: 1, initialRow: 3, improvedRow: 3 },
  ];

  return (
    <div className="public-home">
      <section className="home-hero">
        <div className="welcome-copy">
          <span className="landing-eyebrow">Academic scheduling, structured</span>
          <h1>Timetabling built for academia.</h1>
          <p>
            From complex rules to a clear, publishable timetable. Planora helps university teams import data, understand constraints, build drafts, and repair conflicts in one focused workspace.
          </p>
          <div className="landing-actions">
            <a className="landing-primary" href="/login">Explore the workspace <ArrowRight aria-hidden="true" weight="bold" /></a>
            <a className="landing-secondary" href="#process">See the process</a>
          </div>
        </div>
        <div className={`landing-blueprint ${previewImproved ? "improved" : ""}`} aria-label="Interactive academic timetable preview">
          <header>
            <span><strong>Faculty of Engineering</strong><small>Winter planning · Draft 8</small></span>
            <button type="button" className="secondary-button" aria-pressed={previewImproved} onClick={() => setPreviewImproved((current) => !current)}>
              <MagicWand aria-hidden="true" weight="bold" />{previewImproved ? "Reset preview" : "Improve preview"}
            </button>
          </header>
          <div className="landing-preview-status" aria-live="polite">
            {previewImproved ? <CheckCircle aria-hidden="true" weight="fill" /> : <WarningDiamond aria-hidden="true" weight="fill" />}
            <span><strong>{previewImproved ? "Conflict repaired" : "One room conflict"}</strong><small>{previewImproved ? "Score 1,508 · ready for review" : "Score 2,360 · suggestion available"}</small></span>
          </div>
          <div className="landing-calendar">
            <div className="landing-days"><span>Mon</span><span>Tue</span><span>Wed</span><span>Thu</span><span>Fri</span></div>
            <div className="landing-class-grid">
              {previewClasses.map((item) => (
                <article
                  key={item.id}
                  className={`landing-class tone-${item.tone} ${item.id === "systems" && !previewImproved ? "conflicted" : ""}`}
                  style={{ gridColumn: item.column, gridRow: previewImproved ? item.improvedRow : item.initialRow }}
                >
                  <strong>{item.label}</strong><small>{item.detail}</small>
                </article>
              ))}
            </div>
          </div>
        </div>
      </section>

      <section className="landing-process" id="process" aria-label="Planora workflow">
        {[
          [FileArrowUp, "Import", "Bring in courses, rooms, staff, and availability."],
          [ShieldCheck, "Validate", "Check hard rules before building a draft."],
          [MagicWand, "Build", "Generate and improve an explainable timetable."],
          [WarningDiamond, "Review", "Resolve conflicts with concrete suggestions."],
          [UsersThree, "Publish", "Share the approved schedule by role and group."],
        ].map(([Icon, title, copy]) => (
          <article key={String(title)}><Icon aria-hidden="true" /><span><strong>{String(title)}</strong><small>{String(copy)}</small></span></article>
        ))}
      </section>

      <section className="public-section landing-capabilities">
        <div className="section-title">
          <span className="landing-eyebrow">Built around academic decisions</span>
          <h2>See conflicts, quality, and repair options clearly.</h2>
          <p>Every stage stays inspectable, from imported resources to the final role-filtered timetable.</p>
        </div>
        <div className="landing-feature-grid" aria-label="Planora capabilities">
          <article><span className="feature-icon"><WarningDiamond aria-hidden="true" weight="duotone" /></span><div>
            <strong>Hard conflict visibility</strong>
            <p>Room, staff, and group overlaps are surfaced before admins publish changes.</p>
          </div></article>
          <article><span className="feature-icon"><ShieldCheck aria-hidden="true" weight="duotone" /></span><div>
            <strong>Quality drivers explained</strong>
            <p>Quality terms explain why a timetable score is high and where to focus improvement.</p>
          </div></article>
          <article><span className="feature-icon"><MagicWand aria-hidden="true" weight="duotone" /></span><div>
            <strong>Repair choices in context</strong>
            <p>Admins can hold an activity and see viable target cells with score deltas.</p>
          </div></article>
        </div>
      </section>
    </div>
  );
}


export function FaqContent() {
  return (
    <div className="faq-page">
      <section className="panel faq-hero">
        <h1>FAQ</h1>
        <p>Short answers for students, professors, TAs, and university admins using Planora.</p>
      </section>
      <section className="faq-grid">
        {[
          ["What is Planora?", "A timetable planning system that combines imports, CP-SAT solving, local search improvement, conflict diagnostics, and role-based schedule viewing."],
          ["Who can use it?", "Students can view their group schedule, professors and TAs can view assignments, university admins can solve and repair schedules, and global admins can manage all tenants."],
          ["What are invite codes?", "Invite codes are used after account creation. They let a signed-in user join a university group and receive the schedule visibility or editing permissions assigned to that group."],
          ["Can one user join multiple organizations?", "Yes. Use My Groups after login to redeem invite codes for different universities, then switch the active organization from the account page."],
          ["Do you use analytics cookies?", "Analytics is optional. Essential cookies support login, CSRF protection, and consent. First-party analytics cookies are only set if you opt in."],
          ["Where is the data stored?", "The production Docker deployment stores SQLite data in the planora-data volume."],
        ].map(([question, answer]) => (
          <article className="faq-card" key={question}>
            <h2>{question}</h2>
            <p>{answer}</p>
          </article>
        ))}
      </section>
    </div>
  );
}


export function PrivacyContent() {
  return (
    <div className="faq-page">
      <section className="panel faq-hero">
        <h1>Privacy</h1>
        <p>Planora keeps operational scheduling data tenant-scoped and uses only essential cookies unless analytics is explicitly enabled.</p>
      </section>
      <section className="faq-grid">
        {[
          ["Essential cookies", "Login sessions, CSRF protection, and cookie consent are required for the app to work securely."],
          ["Analytics cookies", "Optional first-party analytics records page views and product events with a pseudonymous client ID. You can opt out from the footer at any time."],
          ["University separation", "Each organization has its own tenant scope. Students, TAs, professors, and university admins only see data permitted by their role and active organization."],
          ["Admin visibility", "Global admins can review audit events, analytics totals, and operational health across tenants for support and abuse prevention."],
          ["Data exports", "Admins can export audit and analytics CSVs from the Admin page. Schedule CSV imports and exports stay inside the authenticated organization workflow."],
          ["Email", "Planora sends verification, password reset, and deliverability-test emails through the configured SMTP provider."],
        ].map(([question, answer]) => (
          <article className="faq-card" key={question}>
            <h2>{question}</h2>
            <p>{answer}</p>
          </article>
        ))}
      </section>
    </div>
  );
}
