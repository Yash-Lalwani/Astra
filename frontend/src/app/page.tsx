const specialists = [
  {
    number: "01",
    name: "Missing Results",
    description: "Looks for completed trials whose required results are overdue.",
  },
  {
    number: "02",
    name: "Broken Promises",
    description: "Compares registered primary outcomes with results and linked papers.",
  },
  {
    number: "03",
    name: "Track Record",
    description: "Examines how reliably a sponsor posts results when they are due.",
  },
  {
    number: "04",
    name: "Pattern Finder",
    description: "Finds reporting patterns that stand apart from comparable studies.",
  },
  {
    number: "05",
    name: "Side Effect Checker",
    description: "Checks whether serious adverse events appear in the registry but not linked abstracts.",
  },
  {
    number: "06",
    name: "Timeline Analyst",
    description: "Spots studies that have drifted well past their own stated schedule.",
  },
];

function AstraMark() {
  return (
    <svg viewBox="0 0 38 38" fill="none" aria-hidden="true" className="brand-mark">
      <path d="M19 3.5v31M3.5 19h31M8 8l22 22M30 8 8 30" stroke="currentColor" strokeWidth="1.7" />
      <circle cx="19" cy="19" r="4.3" fill="currentColor" />
    </svg>
  );
}

function ArrowIcon() {
  return (
    <svg viewBox="0 0 20 20" fill="none" aria-hidden="true" className="arrow-icon">
      <path d="M3 10h13m-5-5 5 5-5 5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export default function Home() {
  return (
    <>
      <header className="site-header">
        <div className="shell header-inner">
          <a className="brand" href="#top" aria-label="Astra home">
            <AstraMark />
            <span>Astra<span className="brand-period">.</span></span>
          </a>
          <nav className="main-nav" aria-label="Main navigation">
            <a href="#approach">Approach</a>
            <a href="#specialists">Specialists</a>
            <a href="#review">Human review</a>
          </nav>
          <a
            className="header-link"
            href="https://astra-production-a9f3.up.railway.app/docs"
            target="_blank"
            rel="noopener noreferrer"
          >
            API docs <span aria-hidden="true">↗</span>
          </a>
        </div>
      </header>

      <main id="top">
        <section className="hero shell" aria-labelledby="hero-title">
          <div className="hero-copy">
            <p className="intro-line"><span className="intro-dot" /> An introduction to Astra</p>
            <h1 id="hero-title">Clinical trial reporting, <em>under a clearer lens.</em></h1>
            <p className="hero-description">
              Astra brings six AI specialists to public trial records and research abstracts. It looks for gaps between what was registered, what was reported, and what was published—then makes the evidence available for human review.
            </p>
            <div className="hero-actions">
              <a className="primary-button" href="#approach">Explore the approach <ArrowIcon /></a>
              <a className="text-link" href="#specialists">Meet the specialists <span aria-hidden="true">↓</span></a>
            </div>
            <div className="source-line">
              <span className="source-rule" />
              Built around public ClinicalTrials.gov records and PubMed abstracts
            </div>
          </div>

          <div className="hero-visual" aria-label="Illustration of the Astra analysis process">
            <div className="visual-topline">
              <span>Astra / analysis path</span>
              <span className="visual-index">01—04</span>
            </div>
            <div className="visual-title">A question becomes an evidence-led brief.</div>
            <div className="process-map">
              <div className="process-row">
                <span className="process-number">01</span>
                <div className="process-content">
                  <strong>Public sources</strong>
                  <div className="source-tags"><span>ClinicalTrials.gov</span><span>PubMed</span></div>
                </div>
                <span className="process-symbol" aria-hidden="true">↘</span>
              </div>
              <div className="process-row active-row">
                <span className="process-number">02</span>
                <div className="process-content">
                  <strong>Specialists investigate</strong>
                  <span>Relevant agents work in parallel</span>
                  <div className="agent-lines" aria-hidden="true"><i /><i /><i /><i /><i /><i /></div>
                </div>
                <span className="process-symbol" aria-hidden="true">✳</span>
              </div>
              <div className="process-row">
                <span className="process-number">03</span>
                <div className="process-content">
                  <strong>Evidence is checked</strong>
                  <span>Claims are validated against records</span>
                </div>
                <span className="process-symbol" aria-hidden="true">✓</span>
              </div>
              <div className="process-row last-row">
                <span className="process-number">04</span>
                <div className="process-content">
                  <strong>Human judgment stays in the loop</strong>
                  <span>Uncertain findings wait for review</span>
                </div>
                <span className="process-symbol" aria-hidden="true">◎</span>
              </div>
            </div>
            <div className="visual-footer"><span className="visual-footer-dot" /> A transparent path from source to signal</div>
          </div>
        </section>

        <div className="disclaimer-band">
          <div className="shell disclaimer-inner">
            <span className="disclaimer-icon" aria-hidden="true">i</span>
            <p>Signals are leads for human review, not findings of misconduct.</p>
            <span className="disclaimer-note">Astra’s guiding principle</span>
          </div>
        </div>

        <section className="approach-section shell section-grid" id="approach" aria-labelledby="approach-title">
          <div className="section-lead">
            <p className="section-number">01 / The approach</p>
            <h2 id="approach-title">Facts first.<br /><em>Judgment second.</em></h2>
          </div>
          <div className="approach-content">
            <p className="large-copy">Astra is designed to make an investigation understandable, from the original public record to the reason a signal was raised.</p>
            <div className="principle-list">
              <div className="principle">
                <span>Compute</span>
                <p>Python and SQL calculate dates, reporting rates, outcome comparisons, and adverse event counts.</p>
              </div>
              <div className="principle">
                <span>Interpret</span>
                <p>Specialist agents assess those facts, explain what may matter, and cite the relevant trial or paper.</p>
              </div>
              <div className="principle">
                <span>Check</span>
                <p>A validator screens unsupported signals before results are saved or sent for review.</p>
              </div>
            </div>
          </div>
        </section>

        <section className="specialists-section" id="specialists" aria-labelledby="specialists-title">
          <div className="shell">
            <div className="specialists-heading">
              <div>
                <p className="section-number">02 / The specialists</p>
                <h2 id="specialists-title">Six ways to look closer.</h2>
              </div>
              <p>Each specialist asks a different question about the same public evidence. The supervisor selects only the ones relevant to a task.</p>
            </div>
            <div className="specialist-list">
              {specialists.map((specialist) => (
                <div className="specialist" key={specialist.number}>
                  <span className="specialist-number">{specialist.number}</span>
                  <h3>{specialist.name}</h3>
                  <p>{specialist.description}</p>
                  <span className="specialist-mark" aria-hidden="true">✳</span>
                </div>
              ))}
            </div>
          </div>
        </section>

        <section className="review-section" id="review" aria-labelledby="review-title">
          <div className="shell review-inner">
            <div className="review-copy">
              <p className="section-number">03 / Human review</p>
              <h2 id="review-title">A signal is a starting point, <em>not a verdict.</em></h2>
              <p>Findings carry citations and confidence scores. Lower-confidence signals enter a review queue; when a reviewer rejects one, Astra turns that feedback into a rule for future runs.</p>
            </div>
            <div className="review-aside">
              <span className="review-aside-icon" aria-hidden="true">✳</span>
              <p>Designed for scrutiny.</p>
              <span>Evidence can be checked. Decisions can be revisited. The system learns from corrections.</span>
            </div>
          </div>
        </section>

        <section className="closing-section shell">
          <div>
            <p className="section-number">What comes next</p>
            <h2>The full workspace<br /><em>is on its way.</em></h2>
          </div>
          <div className="closing-copy">
            <p>This page introduces the research behind Astra. The interactive workspace for exploring signals, watching agents run, and reviewing evidence will follow.</p>
            <a href="https://astra-production-a9f3.up.railway.app/docs" target="_blank" rel="noopener noreferrer">Explore the live API <ArrowIcon /></a>
          </div>
        </section>
      </main>

      <footer className="site-footer">
        <div className="shell footer-inner">
          <a className="brand footer-brand" href="#top" aria-label="Astra, back to top"><AstraMark /><span>Astra<span className="brand-period">.</span></span></a>
          <p>Examining how clinical trials report what happened.</p>
          <a href="#top">Back to top ↑</a>
        </div>
      </footer>
    </>
  );
}
