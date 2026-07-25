"""Interactive website tour catalog for the visual Career Coach."""

from __future__ import annotations

from api.schemas.autopilot import CoachTourStep


def step(
    path: str,
    target: str,
    title: str,
    body: str,
    *,
    placement: str = "bottom",
) -> CoachTourStep:
    return CoachTourStep(
        path=path,
        target=target,
        title=title,
        body=body,
        placement=placement,  # type: ignore[arg-type]
    )


# Targets must match data-coach-id attributes in the React app.
TOURS: dict[str, list[CoachTourStep]] = {
    "site_tour": [
        step(
            "/today",
            "nav-today",
            "Start here — Today",
            "Your daily command center. Autopilot surfaces jobs, follow-ups, and packets to clear.",
            placement="right",
        ),
        step(
            "/today",
            "today-header",
            "Today queue",
            "Work top to bottom: high-score jobs, overdue follow-ups, then interview nudges.",
        ),
        step(
            "/today",
            "today-auto-pipeline",
            "Paste any job",
            "Found a role outside our boards? Paste the JD here to score and optionally tailor.",
        ),
        step(
            "/opportunities",
            "nav-jobs",
            "Browse Jobs",
            "All scored opportunities live here. Filter, approve, skip, or reject — you always apply yourself.",
            placement="right",
        ),
        step(
            "/opportunities",
            "jobs-filters",
            "Filters",
            "Narrow by country, visa, archetype, and score so you only see roles worth your time.",
        ),
        step(
            "/tracker",
            "nav-tracker",
            "Application Tracker",
            "Kanban of every role you approved. Update status after you submit externally.",
            placement="right",
        ),
        step(
            "/tracker",
            "tracker-board",
            "Status columns",
            "Move cards as you progress. Open a card for Apply Packet, messages, and interview prep.",
        ),
        step(
            "/networks",
            "nav-network",
            "Network",
            "Draft LinkedIn outreach and track contacts — you always send the message yourself.",
            placement="right",
        ),
        step(
            "/settings",
            "nav-settings",
            "Settings",
            "Upload your master resume and set preferences so scoring and tailoring stay accurate.",
            placement="right",
        ),
        step(
            "/coach",
            "nav-coach",
            "Ask me anytime",
            "Open Coach or the floating chat. Say “show me how to apply” and I’ll guide you live.",
            placement="right",
        ),
    ],
    "apply_flow": [
        step(
            "/opportunities",
            "nav-jobs",
            "Find a role",
            "Browse Jobs and pick a strong match to approve.",
            placement="right",
        ),
        step(
            "/opportunities",
            "jobs-list",
            "Approve a job",
            "Hit Approve on a card. That creates a tracker entry and starts resume tailoring.",
        ),
        step(
            "/tracker",
            "nav-tracker",
            "Open Tracker",
            "Your approved role appears here under Approved.",
            placement="right",
        ),
        step(
            "/tracker",
            "tracker-board",
            "Finish Apply Packet",
            "Select the card, then use Apply Packet for resume, cover letter, and form drafts. You submit on the company site.",
        ),
    ],
    "follow_ups": [
        step(
            "/today",
            "today-followups",
            "Overdue follow-ups",
            "Start with anything flagged overdue — a short note beats silence.",
        ),
        step(
            "/tracker",
            "nav-tracker",
            "Update Tracker",
            "Open the application, copy a follow-up draft, send it yourself, then mark followed up.",
            placement="right",
        ),
        step(
            "/tracker",
            "tracker-board",
            "Pick the card",
            "Select the applied role to open follow-up tools and notes.",
        ),
    ],
    "jobs_browse": [
        step(
            "/opportunities",
            "nav-jobs",
            "Jobs page",
            "I’ll take you to Opportunities — every scored role in one place.",
            placement="right",
        ),
        step(
            "/opportunities",
            "jobs-filters",
            "Tune filters",
            "Set min score and preferences so weak matches fall away.",
        ),
        step(
            "/opportunities",
            "jobs-list",
            "Review cards",
            "Open details, then Approve when you’re ready to tailor a resume.",
        ),
    ],
    "upload_resume": [
        step(
            "/settings",
            "nav-settings",
            "Settings",
            "Preferences and resume upload live here.",
            placement="right",
        ),
        step(
            "/settings",
            "settings-tabs",
            "Resume tab",
            "Choose Upload Resume, then add your master CV so scoring and tailoring work.",
        ),
        step(
            "/settings",
            "settings-panel",
            "Upload area",
            "Drop your PDF/DOCX. Parsed skills feed the nightly pipeline.",
        ),
    ],
    "network_outreach": [
        step(
            "/networks",
            "nav-network",
            "Network hub",
            "Track recruiters and hiring managers without storing LinkedIn logins.",
            placement="right",
        ),
        step(
            "/networks",
            "network-add",
            "Add a contact",
            "Save people you want to reach, then generate a connect note to paste on LinkedIn.",
        ),
    ],
    "today_focus": [
        step(
            "/today",
            "nav-today",
            "Today",
            "Your prioritized list for this session.",
            placement="right",
        ),
        step(
            "/today",
            "today-header",
            "Work the queue",
            "Clear follow-ups first, then act on high-score jobs and packet gaps.",
        ),
        step(
            "/today",
            "today-jobs",
            "Jobs to act on",
            "These are unscored high-fit roles waiting for a decision.",
        ),
    ],
    "analytics": [
        step(
            "/analytics",
            "nav-analytics",
            "Analytics",
            "Response rates and targeting patterns once you’ve marked enough Applied roles.",
            placement="right",
        ),
        step(
            "/analytics",
            "analytics-patterns",
            "Patterns",
            "See why you reject roles and where follow-ups stall — then adjust targeting.",
        ),
    ],
}


INTENT_RULES: list[tuple[tuple[str, ...], str]] = [
    (("tour", "show me around", "walk me through", "guide me", "tutorial", "how does this work", "onboarding"), "site_tour"),
    (("how do i apply", "apply flow", "application packet", "how to apply", "submit"), "apply_flow"),
    (("follow-up", "follow up", "followup", "overdue"), "follow_ups"),
    (("show.*job", "browse job", "opportunit", "find a role", "top job"), "jobs_browse"),
    (("upload resume", "master resume", "settings", "preferences"), "upload_resume"),
    (("network", "linkedin outreach", "connect note", "recruiter"), "network_outreach"),
    (("what should i do", "today", "next step", "priority"), "today_focus"),
    (("analytics", "pattern", "response rate"), "analytics"),
]


def match_tour(message: str, *, tour_id: str | None = None) -> tuple[str | None, list[CoachTourStep]]:
    """Return (tour_id, steps) from explicit id or keyword intent."""
    if tour_id and tour_id in TOURS:
        return tour_id, list(TOURS[tour_id])

    text = (message or "").strip().lower()
    if not text:
        return None, []

    import re

    for keywords, tid in INTENT_RULES:
        for kw in keywords:
            if "*" in kw or kw.startswith("show"):
                if re.search(kw.replace(" ", r"\s+"), text):
                    return tid, list(TOURS[tid])
            elif kw in text:
                return tid, list(TOURS[tid])
    return None, []


def tour_action_label(tour_id: str) -> str:
    labels = {
        "site_tour": "Start site tour",
        "apply_flow": "Guide me to apply",
        "follow_ups": "Guide follow-ups",
        "jobs_browse": "Show me Jobs",
        "upload_resume": "Guide resume upload",
        "network_outreach": "Guide networking",
        "today_focus": "Walk Today queue",
        "analytics": "Show Analytics",
    }
    return labels.get(tour_id, "Start guided tour")
