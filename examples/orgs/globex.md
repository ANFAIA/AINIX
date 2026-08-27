# Globex — a 200-person B2B SaaS company

Richer than ACME on purpose: more groups, real conflicts of interest between
them, and one function (support) that reads untrusted customer input all day.

## Functions

**Revenue** — outbound sequences, lead qualification, and keeping the CRM
honest. Needs to know what the product does but must never see unreleased
roadmap: a salesperson repeating a draft feature to a prospect is how
commitments get made by accident.

**Support** — answers customer tickets, triages bugs, and writes public help
articles. Reads whatever a customer sends, including attachments. Must be able
to reach engineering's bug tracker but not engineering's design documents.

**Engineering** — triages incoming bugs, drafts release notes, and reviews
dependency updates for security advisories. Sees unreleased work.

**Finance** — invoices, spend against budget, and renewal forecasting. Sees
customer contract values, which nobody else should.

**People** — hiring pipeline and onboarding. Handles personal data about
candidates and employees, which is the most sensitive material in the company
even though it is the least commercially interesting.

**Knowledge** — custody of every document and the memory built from them.
Brokers reads for everyone else.

## Constraints

- A person talks to Globex through a single console.
- Support reads untrusted input, so it must be the least privileged function
  that still does useful work.
- Nothing publishes to customers without a human approving the text.
- Finance and People each hold material the other must not see, even though
  both are highly cleared.
