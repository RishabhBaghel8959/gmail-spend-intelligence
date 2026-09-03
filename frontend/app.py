"""Gmail Spend Intelligence — Streamlit frontend.

A thin dashboard over the FastAPI backend. It never talks to MongoDB or Gmail
directly: everything goes through the backend's HTTP API. Run it with:

    streamlit run frontend/app.py

and make sure the backend is running at BACKEND_URL (default localhost:8000).
"""
from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import requests
import streamlit as st

BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000").rstrip("/")
# ``BACKEND_URL`` can be an internal Docker hostname (``http://backend:8000``),
# which the browser cannot resolve. Use this public URL for browser redirects.
PUBLIC_BACKEND_URL = os.environ.get("PUBLIC_BACKEND_URL", BACKEND_URL).rstrip("/")
REQUEST_TIMEOUT = 120  # a sync can take a while (fetching + extracting emails)

CURRENCY_SYMBOLS = {"INR": "₹", "USD": "$", "EUR": "€", "GBP": "£"}

st.set_page_config(page_title="Gmail Spend Intelligence", page_icon="💸", layout="wide")


# --------------------------------------------------------------------------- #
# Backend helpers
# --------------------------------------------------------------------------- #
class BackendError(Exception):
    """Raised when the backend is unreachable or returns an error."""


def _request(method: str, path: str, **kwargs):
    """Call the backend and turn failures into a friendly BackendError."""
    url = f"{BACKEND_URL}{path}"
    try:
        resp = requests.request(method, url, timeout=REQUEST_TIMEOUT, **kwargs)
    except requests.exceptions.RequestException as exc:
        raise BackendError(
            f"Could not reach the backend at {BACKEND_URL}. Is it running? "
            f"(uvicorn app.main:app --port 8000)\n\nDetails: {exc}"
        ) from exc

    if resp.status_code >= 400:
        # Surface the backend's own error message where possible.
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise BackendError(f"{resp.status_code}: {detail}")

    if resp.status_code == 204 or not resp.content:
        return None
    return resp.json()


def get_status() -> dict:
    return _request("GET", "/auth/status")


def get_profile() -> dict:
    return _request("GET", "/profile")


def get_insights() -> dict:
    return _request("GET", "/insights")


def get_transactions() -> list[dict]:
    return _request("GET", "/transactions", params={"limit": 1000}) or []


def run_sync(months: int, max_emails: int) -> dict:
    return _request(
        "POST", "/sync", json={"months": months, "max_emails": max_emails}
    )


def logout() -> None:
    _request("POST", "/auth/logout")


def money(amount: float | None, currency: str = "INR") -> str:
    if amount is None:
        return "—"
    sym = CURRENCY_SYMBOLS.get(currency, currency + " ")
    if float(amount).is_integer():
        return f"{sym}{amount:,.0f}"
    return f"{sym}{amount:,.2f}"


# --------------------------------------------------------------------------- #
# One-time handling of the OAuth redirect (?connected=... / ?auth_error=...)
# --------------------------------------------------------------------------- #
def handle_redirect_params() -> None:
    params = st.query_params
    if "connected" in params:
        st.session_state["flash_success"] = f"Connected {params['connected']} ✅"
        st.query_params.clear()
    elif "auth_error" in params:
        st.session_state["flash_error"] = (
            f"Google sign-in failed: {params['auth_error']}. Please try again."
        )
        st.query_params.clear()


# --------------------------------------------------------------------------- #
# Sidebar: connection + sync controls
# --------------------------------------------------------------------------- #
def render_sidebar(status: dict) -> None:
    with st.sidebar:
        st.header("Gmail connection")

        if not status["configured"]:
            st.warning(
                "Google OAuth isn't configured yet. Add GOOGLE_CLIENT_ID and "
                "GOOGLE_CLIENT_SECRET to `backend/.env` (see the README), then "
                "restart the backend."
            )
            return

        if status["connected"]:
            st.success(f"Connected as **{status['email']}**")
            if st.button("Disconnect", use_container_width=True):
                try:
                    logout()
                    st.session_state["flash_success"] = "Disconnected."
                    st.rerun()
                except BackendError as exc:
                    st.error(str(exc))
        else:
            st.info("Connect your Gmail to analyze your spending.")
            st.link_button(
                "🔗 Connect Gmail",
                f"{PUBLIC_BACKEND_URL}/auth/google/login",
                use_container_width=True,
            )
            st.caption(
                "Read-only access (gmail.readonly). We never send, modify, or "
                "delete your email."
            )

        st.divider()
        st.header("Sync")
        st.caption("Scan recent emails and extract transactions.")
        months = st.slider("Look back (months)", 1, 24, 6)
        max_emails = st.slider("Max emails to scan", 20, 500, 150, step=10)

        disabled = not status["connected"]
        if st.button("🔄 Sync now", use_container_width=True, disabled=disabled):
            with st.spinner("Fetching and analyzing your emails… this can take a minute."):
                try:
                    result = run_sync(months, max_emails)
                    st.session_state["last_sync"] = result
                    st.session_state["flash_success"] = (
                        result.get("message") or "Sync complete."
                    )
                    st.rerun()
                except BackendError as exc:
                    st.session_state["flash_error"] = str(exc)
                    st.rerun()

        last = st.session_state.get("last_sync")
        if last:
            st.caption(
                f"Last sync: {last.get('new_transactions', 0)} new / "
                f"{last.get('transactions_found', 0)} found "
                f"from {last.get('emails_scanned', 0)} emails."
            )


# --------------------------------------------------------------------------- #
# Dashboard sections
# --------------------------------------------------------------------------- #
def render_kpis(profile: dict) -> None:
    cur = profile.get("currency", "INR")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total spent", money(profile.get("total_spent"), cur))
    c2.metric("Transactions", profile.get("spend_transaction_count", 0))
    c3.metric("Recurring / mo", money(profile.get("recurring_monthly_estimate"), cur))
    span = "—"
    if profile.get("first_date") and profile.get("last_date"):
        span = f"{profile['first_date']} → {profile['last_date']}"
    c4.metric("Date range", span)


def render_charts(profile: dict) -> None:
    cur = profile.get("currency", "INR")
    left, right = st.columns(2)

    with left:
        st.subheader("Spending by category")
        cats = profile.get("by_category", [])
        if cats:
            df = pd.DataFrame(cats)
            fig = px.pie(df, names="category", values="amount", hole=0.45)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(showlegend=True, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No category data yet.")

    with right:
        st.subheader("Monthly trend")
        monthly = profile.get("monthly", [])
        if monthly:
            df = pd.DataFrame(monthly)
            fig = px.bar(df, x="month", y="amount")
            fig.update_layout(
                margin=dict(t=10, b=10, l=10, r=10),
                yaxis_title=f"Amount ({cur})", xaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.caption("No monthly data yet.")

    st.subheader("Top merchants")
    merchants = profile.get("by_merchant", [])
    if merchants:
        df = pd.DataFrame(merchants).sort_values("amount", ascending=True)
        fig = px.bar(df, x="amount", y="merchant", orientation="h")
        fig.update_layout(
            margin=dict(t=10, b=10, l=10, r=10),
            xaxis_title=f"Amount ({cur})", yaxis_title="",
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.caption("No merchant data yet.")


def render_insights(insights: dict) -> None:
    anomalies = insights.get("anomalies", [])
    all_insights = insights.get("insights", [])

    st.subheader("⚠️ Flagged for your attention")
    if anomalies:
        for a in anomalies:
            st.warning(f"**{a['title']}** — {a['text']}")
    else:
        st.caption("Nothing unusual detected.")

    informational = [i for i in all_insights if i.get("severity") != "warning"]
    if informational:
        st.subheader("💡 Insights")
        for i in informational:
            st.info(f"**{i['title']}** — {i['text']}")


def render_recurring(profile: dict) -> None:
    recurring = profile.get("recurring", [])
    st.subheader("🔁 Recurring payments")
    if not recurring:
        st.caption("No recurring payments detected yet.")
        return
    cur = profile.get("currency", "INR")
    rows = [
        {
            "Merchant": r["merchant"],
            "Category": r["category"],
            "Cadence": r["cadence"],
            "Avg amount": money(r["average_amount"], cur),
            "Occurrences": r["occurrences"],
            "Last charged": r["last_date"],
            "Next expected": r.get("next_expected") or "—",
        }
        for r in recurring
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)


def render_transactions(transactions: list[dict]) -> None:
    st.subheader("🧾 Transactions")
    if not transactions:
        st.caption("No transactions yet. Run a sync to populate this.")
        return

    df = pd.DataFrame(transactions)
    # Category filter
    cats = ["All"] + sorted(df["category"].dropna().unique().tolist())
    chosen = st.selectbox("Filter by category", cats)
    if chosen != "All":
        df = df[df["category"] == chosen]

    view = pd.DataFrame(
        {
            "Date": df["date"],
            "Merchant": df["merchant"],
            "Amount": [money(a, c) for a, c in zip(df["amount"], df["currency"])],
            "Category": df["category"],
            "Type": df["txn_type"],
            "Subject": df["subject"],
            "Email": df["gmail_link"],
        }
    )
    st.dataframe(
        view,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Email": st.column_config.LinkColumn("Email", display_text="Open ↗"),
        },
    )
    st.caption(f"{len(view)} transaction(s). Click **Open** to see the source email.")


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> None:
    handle_redirect_params()

    st.title("💸 Gmail Spend Intelligence")
    st.caption(
        "Understand your spending from your inbox — categories, recurring "
        "payments, and unusual charges, each traceable to the source email."
    )

    # Flash messages from the previous run (e.g. after connect/sync/redirect).
    if msg := st.session_state.pop("flash_success", None):
        st.success(msg)
    if msg := st.session_state.pop("flash_error", None):
        st.error(msg)

    # Everything below needs the backend; if it's down, say so clearly and stop.
    try:
        status = get_status()
    except BackendError as exc:
        st.error(str(exc))
        st.stop()

    render_sidebar(status)

    if not status["connected"]:
        st.info(
            "👈 Connect your Gmail account from the sidebar to get started."
            if status["configured"]
            else "👈 Configure Google OAuth (see the sidebar) to get started."
        )
        return

    # Connected: load data.
    try:
        profile = get_profile()
        insights = get_insights()
        transactions = get_transactions()
    except BackendError as exc:
        st.error(str(exc))
        return

    if profile.get("transaction_count", 0) == 0:
        st.info(
            "No transactions yet. Use **Sync now** in the sidebar to scan your "
            "recent emails."
        )
        return

    render_kpis(profile)
    st.divider()
    render_insights(insights)
    st.divider()
    render_charts(profile)
    st.divider()
    render_recurring(profile)
    st.divider()
    render_transactions(transactions)


if __name__ == "__main__":
    main()
