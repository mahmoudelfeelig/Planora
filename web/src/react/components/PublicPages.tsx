export function HomeContent() {
  return (
    <div className="public-home">
      <section className="home-hero">
        <div className="welcome-copy">
          <h1>Explainable scheduling for real university constraints.</h1>
          <p>
            Planora imports timetable data, detects hard conflicts, scores schedule quality, and shows repair choices clearly for students, lecturers, TAs, and administrators.
          </p>
          <div className="hero-stats" aria-label="Planora summary metrics">
            <span><strong>16</strong> conflict types surfaced</span>
            <span><strong>10x</strong> penalty reductions on tuned runs</span>
            <span><strong>Roles</strong> filtered by organization</span>
          </div>
        </div>
        <div
          className="schedule-demo"
          role="img"
          aria-label="Animated one-week repair simulation showing a high-penalty schedule with conflicts becoming a cleaner schedule after two improvement runs."
        >
          <div className="demo-head">
            <span>One-week repair simulation</span>
            <div className="demo-score">
              <strong>14552</strong>
              <i />
              <strong>1508</strong>
            </div>
          </div>
          <div className="demo-stage">
            <div className="demo-grid-lines" />
            {[
              {
                label: "Run 0",
                penalty: "14552",
                note: "16 conflicts",
                status: "conflict",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["clash conflict", "TUE", "11:00", "A50/A51 room clash", 2, 2, 2],
                  ["lec", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 1",
                penalty: "8820",
                note: "9 conflicts",
                status: "repairing",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["clash conflict", "TUE", "11:00", "A51 clash", 2, 2, 1],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["lec", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 2",
                penalty: "4210",
                note: "3 conflicts",
                status: "repairing",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["tut", "TUE", "13:00", "A51 Tutorial", 2, 3, 1],
                  ["lec", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 3",
                penalty: "2360",
                note: "1 conflict",
                status: "repairing",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["tut shifted", "FRI", "11:00", "A51 Tutorial", 5, 2, 1],
                  ["lec same", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
              {
                label: "Run 4",
                penalty: "1508",
                note: "clean",
                status: "clean",
                blocks: [
                  ["lec wide", "MON", "09:00", "A45 Lecture", 1, 1, 2],
                  ["lab moved", "WED", "11:00", "A50 Lab", 3, 2, 1],
                  ["tut shifted", "FRI", "11:00", "A51 Tutorial", 4, 1, 2],
                  ["lec same", "THU", "13:00", "A82 Lecture", 4, 3, 2],
                ],
              },
            ].map((run, runIndex) => (
              <div key={run.label} className={`demo-run run-${runIndex}`}>
                <div className="run-label">
                  <strong>{run.label}</strong>
                  <span>{run.note}</span>
                </div>
                <div className={`run-status ${run.status}`}>{run.penalty}</div>
                {run.blocks.map(([kind, day, time, label, column, row, span]) => (
                  <span
                    key={`${run.label}-${label}`}
                    className={`demo-block ${kind}`}
                    style={{
                      gridColumn: `${column} / span ${span}`,
                      gridRow: `${Number(row) + 1}`,
                    }}
                  >
                    <b>{label}</b>
                    <small>{day} {time}</small>
                  </span>
                ))}
              </div>
            ))}
          </div>
          <div className="demo-days">
            {["MON", "TUE", "WED", "THU", "FRI"].map((day) => <span key={day}>{day}</span>)}
          </div>
        </div>
      </section>

      <section className="public-section">
        <div className="section-title">
          <h2>See conflicts, quality, and repair options clearly</h2>
          <p>Planora turns raw timetable data into explainable dashboards: conflict lists, penalty drivers, local-search improvements, and role-filtered schedule views.</p>
        </div>
        <div className="visual-grid" aria-label="Planora capabilities">
          <article>
            <strong>Hard conflict visibility</strong>
            <div className="bar-chart"><span style={{ height: "70%" }} /><span style={{ height: "38%" }} /><span style={{ height: "12%" }} /></div>
            <p>Room, staff, and group overlaps are surfaced before admins publish changes.</p>
          </article>
          <article>
            <strong>Penalty driver breakdown</strong>
            <div className="donut-chart" />
            <p>Quality terms explain why a timetable score is high and where to focus improvement.</p>
          </article>
          <article>
            <strong>Move previews</strong>
            <div className="target-grid"><span /><span className="ok" /><span /><span className="warn" /><span className="ok" /><span /></div>
            <p>Admins can hold an activity and see viable target cells with score deltas.</p>
          </article>
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
