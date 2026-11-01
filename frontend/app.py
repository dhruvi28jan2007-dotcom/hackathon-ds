import os
import sys
from pathlib import Path

# Ensure project root is in sys.path
root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))

import streamlit as st

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from ai_engine.client import get_ai_client
from ai_engine.open_weight_client import OpenWeightAIClient
from ai_engine.mock_client import MockAIClient
from ai_engine.interface import AIServerUnavailableError, AIError, AIProhibitedModelError
from backend.models import PullRequest, InvestigationResult
from backend.orchestrator import InvestigationOrchestrator
from integrations.github_client import GitHubClientError
from database.db import list_investigations, get_investigation
from reports.passport import generate_markdown_passport, generate_json_passport

# Page configuration
st.set_page_config(
    page_title="ClaimCheck — GitHub PR Verifier",
    page_icon="🛡️",
    layout="wide",
)

st.title("🛡️ ClaimCheck")
st.caption("Automated GitHub Pull Request Verification using Approved Open-Weight Models (Qwen 2.5 7B)")

# Sidebar: AI Model Configuration & Health
st.sidebar.header("⚙️ Model Configuration")

env_provider = os.getenv("AI_PROVIDER", "mock")
provider_options = ["mock", "organizer_server", "local"]
default_idx = provider_options.index(env_provider) if env_provider in provider_options else 0

selected_provider = st.sidebar.selectbox(
    "AI Provider",
    options=provider_options,
    index=default_idx,
    help="ClaimCheck runs strictly on approved open-weight models or offline mock.",
)

default_base_url = os.getenv("AI_BASE_URL", "http://localhost:11434/v1" if selected_provider != "mock" else "")
base_url_input = st.sidebar.text_input(
    "Model Server Base URL",
    value=default_base_url,
    placeholder="e.g. http://localhost:11434/v1",
    disabled=(selected_provider == "mock"),
)

default_model = os.getenv("AI_MODEL", "qwen2.5:7b" if selected_provider != "mock" else "")
model_input = st.sidebar.text_input(
    "Open-Weight Model Name",
    value=default_model,
    placeholder="e.g. qwen2.5:7b",
    disabled=(selected_provider == "mock"),
)

# Initialize AI Client
ai_client = None
client_status_msg = ""
client_is_healthy = False
effective_provider = selected_provider  # may become "mock" if real server is unavailable

try:
    if selected_provider == "mock":
        ai_client = MockAIClient()
        client_is_healthy, client_status_msg = ai_client.check_health()
    else:
        real_client = OpenWeightAIClient(
            base_url=base_url_input,
            model=model_input,
        )
        client_is_healthy, client_status_msg = real_client.check_health()
        if client_is_healthy:
            ai_client = real_client
        else:
            # Real server unreachable — do NOT silently fall back to mock.
            # Surface the error so the user can decide.
            ai_client = None
except AIProhibitedModelError as exc:
    st.sidebar.error(f"🚫 Rule Violation: {exc}")
except AIError as exc:
    st.sidebar.warning(f"⚠️ AI Config: {exc}")
except Exception as exc:
    st.sidebar.error(f"❌ Error: {exc}")

# ── Sidebar status badge ──────────────────────────────────────────────────────
if selected_provider == "mock":
    st.sidebar.warning(
        "🟡 **MOCK MODE** — Keyword-based inference only.  \n"
        "Results are NOT from a real open-weight model.  \n"
        "Switch to `local` or `organizer_server` for genuine Qwen 2.5 7B inference."
    )
elif client_is_healthy:
    st.sidebar.success(f"🟢 Real model connected: {client_status_msg}")
else:
    st.sidebar.error(
        f"🔴 **Real model unavailable** — {client_status_msg}  \n\n"
        "Start Ollama (`ollama serve`) or point to the organizer server, "
        "then refresh. Audit is blocked until the model is reachable."
    )

st.sidebar.markdown("---")
st.sidebar.markdown("**Hackathon Rule Compliance:**")
st.sidebar.markdown("- ✅ Zero closed-model APIs (OpenAI/Claude/Gemini blocked)")
st.sidebar.markdown("- ✅ Approved open-weight model: Qwen 2.5 7B")
st.sidebar.markdown("- ✅ Deterministic mock support for offline audit")

# History Sidebar
st.sidebar.markdown("---")
st.sidebar.subheader("📜 Recent Investigations")
recent_invs = list_investigations(limit=5)
if recent_invs:
    for inv in recent_invs:
        btn_label = f"#{inv['pr_number']} {inv['pr_owner']}/{inv['pr_repo']}"
        if st.sidebar.button(btn_label, key=f"hist_{inv['id']}"):
            loaded = get_investigation(inv["id"])
            if loaded:
                st.session_state["current_result"] = loaded
                st.rerun()
else:
    st.sidebar.caption("No investigations yet.")


# Main Interface Tabs
tab_verify, tab_history = st.tabs(["🚀 Verify Pull Request", "📚 Investigation History"])

with tab_verify:
    st.markdown("Enter a public GitHub Pull Request URL to audit its claims against the submitted code changes.")

    col1, col2 = st.columns([3, 1])
    with col1:
        pr_url_input = st.text_input(
            "GitHub PR URL",
            placeholder="https://github.com/owner/repository/pull/123",
            value="",
        )
    with col2:
        use_sample_data = st.checkbox("Use Demo / Sample PR", value=False)

    sample_diff_content = None
    sample_pr_obj = None

    if use_sample_data:
        st.info("💡 Demo mode activated: auditing a sample PR fixing token session validation.")
        sample_pr_obj = PullRequest(
            owner="axiom-team",
            repo="claimcheck-core",
            number=42,
            title="Enforce session expiration checks and auto-reconnect",
            description=(
                "Summary of changes:\n"
                "1. Validates token expiration before processing sensitive requests.\n"
                "2. Auto-reconnects database connection if drop is detected.\n"
                "3. Rejects expired sessions with AuthError."
            ),
            url="https://github.com/axiom-team/claimcheck-core/pull/42",
            base_sha="a1b2c3d4",
            head_sha="e5f6g7h8",
        )
        sample_diff_content = """diff --git a/services/auth.py b/services/auth.py
index 1029384..5647382 100644
--- a/services/auth.py
+++ b/services/auth.py
@@ -20,6 +20,12 @@ def validate_session(token: str) -> bool:
     if not token:
         return False
+    if token_provider.is_expired(token):
+        raise AuthError("Token has expired")
+    return True
diff --git a/database/pool.py b/database/pool.py
index abcdef0..1234567 100644
--- a/database/pool.py
+++ b/database/pool.py
@@ -45,4 +45,9 @@ def execute_query(query: str):
     except ConnectionDropError:
+        logger.warning("Reconnecting to DB...")
+        reconnect()
+        return execute_query(query)
"""

    if st.button("🔍 Run ClaimCheck Audit", type="primary", use_container_width=True):
        if not use_sample_data and not pr_url_input.strip():
            st.error("Please enter a valid GitHub Pull Request URL or check 'Use Demo / Sample PR'.")
        elif not ai_client:
            st.error(
                "AI Client is not configured or real model server is unreachable. "
                "Check the sidebar settings. Start Ollama or select 'mock' for offline audit."
            )
        else:
            # Surface inference mode clearly before running
            if isinstance(ai_client, MockAIClient):
                st.warning(
                    "⚠️ **MOCK MODE ACTIVE** — This audit uses keyword-based inference, "
                    "not genuine Qwen 2.5 7B model execution. "
                    "Results are illustrative only and must not be treated as authoritative AI verification."
                )
            with st.spinner("Analyzing PR, extracting claims, and verifying code evidence..."):
                try:
                    orchestrator = InvestigationOrchestrator(ai_client=ai_client)
                    result = orchestrator.run_investigation(
                        pr_url=pr_url_input if not use_sample_data else sample_pr_obj.url,
                        sample_diff=sample_diff_content,
                        sample_pr=sample_pr_obj,
                    )
                    st.session_state["current_result"] = result
                    st.session_state["result_used_mock"] = orchestrator.using_mock
                    st.success("Investigation complete!")
                except GitHubClientError as exc:
                    st.error(f"🐙 GitHub Error: {exc}")
                except AIServerUnavailableError as exc:
                    st.error(f"🔴 AI Server Unavailable: {exc}")
                except Exception as exc:
                    st.error(f"Investigation failed: {exc}")

    # Display Current Result
    current_result: InvestigationResult | None = st.session_state.get("current_result")

    if current_result:
        st.markdown("---")
        pr = current_result.pull_request

        # ── Inference mode badge ──────────────────────────────────────────────
        result_used_mock = st.session_state.get("result_used_mock", True)
        if result_used_mock:
            st.warning(
                "🟡 **MOCK INFERENCE** — These results were produced by keyword-based mock logic, "
                "NOT by the Qwen 2.5 7B open-weight model. "
                "Switch to `local` or `organizer_server` in the sidebar for real AI inference."
            )
        else:
            st.success("🟢 **REAL MODEL INFERENCE** — Results produced by the approved open-weight model.")

        st.subheader(f"Results for PR #{pr.number}: {pr.title}")
        st.caption(f"Repository: `{pr.owner}/{pr.repo}` | [View on GitHub]({pr.url}) | ID: `{current_result.investigation_id}`")

        # Scorecard metrics
        supported_cnt = sum(1 for v in current_result.verdicts if v.status == "supported")
        part_cnt = sum(1 for v in current_result.verdicts if v.status == "partially_supported")
        contra_cnt = sum(1 for v in current_result.verdicts if v.status == "contradicted")
        insuf_cnt = sum(1 for v in current_result.verdicts if v.status == "insufficient_evidence")

        m1, m2, m3, m4, m5 = st.columns(5)
        m1.metric("Claims Extracted", len(current_result.claims))
        m2.metric("✅ Supported", supported_cnt)
        m3.metric("⚠️ Partial", part_cnt)
        m4.metric("❌ Contradicted", contra_cnt)
        m5.metric("❓ Insufficient", insuf_cnt)

        # Tabs for detailed inspection
        res_tab1, res_tab2, res_tab3, res_tab4 = st.tabs([
            "📋 Claims & Verdicts",
            "🔍 Code Evidence",
            "🧪 Test Scenarios",
            "📄 Evidence Passport",
        ])

        with res_tab1:
            verdicts_map = {v.claim_id: v for v in current_result.verdicts}
            for claim in current_result.claims:
                v = verdicts_map.get(claim.id)
                status_color = {
                    "supported": "green",
                    "partially_supported": "orange",
                    "contradicted": "red",
                    "insufficient_evidence": "gray",
                }.get(v.status if v else "", "blue")

                with st.expander(f"**{claim.id.upper()}**: {claim.description}", expanded=True):
                    col_a, col_b = st.columns([3, 1])
                    with col_a:
                        st.markdown(f"**Category:** `{claim.category}` | **Source ({claim.source_type}):** *\"{claim.source_text}\"*")
                    with col_b:
                        if v:
                            st.markdown(f"**Verdict:** :{status_color}[**{v.status.upper()}**]")

                    if v:
                        st.markdown(f"**Analysis:** {v.reasoning}")
                        if v.limitations:
                            st.markdown("**Limitations:**")
                            for lim in v.limitations:
                                st.markdown(f"- {lim}")

        with res_tab2:
            if current_result.evidence:
                for ev in current_result.evidence:
                    lines_label = f"Lines {ev.start_line}-{ev.end_line}" if ev.start_line else ""
                    st.markdown(f"**`{ev.file_path}`** {lines_label} — `{ev.category}`")
                    st.code(ev.snippet, language="diff")
            else:
                st.info("No code evidence snippets collected for this investigation.")

        with res_tab3:
            if current_result.test_scenarios:
                for sc in current_result.test_scenarios:
                    st.markdown(f"**Claim `{sc.claim_id}`**: {sc.description}")
                    st.caption(f"Expected outcome: {sc.expected_result}")
            else:
                st.info("No test scenarios generated.")

        with res_tab4:
            if result_used_mock:
                active_model = "Mock AI Engine (keyword-based — NOT Qwen 2.5 7B inference)"
                st.warning(
                    "⚠️ This passport was generated using **mock inference**, not a real open-weight model. "
                    "Do not submit this as AI-verified evidence."
                )
            else:
                active_model = model_input or os.getenv("AI_MODEL", "qwen2.5:7b")
            md_passport = generate_markdown_passport(current_result, model_name=active_model)
            json_passport = generate_json_passport(current_result)

            st.download_button(
                "📥 Download Markdown Passport (.md)",
                data=md_passport,
                file_name=f"evidence_passport_{pr.owner}_{pr.repo}_{pr.number}.md",
                mime="text/markdown",
            )
            st.download_button(
                "📥 Download JSON Passport (.json)",
                data=json_passport,
                file_name=f"evidence_passport_{pr.owner}_{pr.repo}_{pr.number}.json",
                mime="application/json",
            )

            st.markdown("### Markdown Preview")
            st.markdown(md_passport)

with tab_history:
    st.subheader("📚 Saved Investigations")
    all_invs = list_investigations(limit=30)
    if not all_invs:
        st.info("No past investigations stored in database.")
    else:
        for item in all_invs:
            col_h1, col_h2 = st.columns([4, 1])
            with col_h1:
                st.markdown(f"**#{item['pr_number']} - {item['pr_title']}** (`{item['pr_owner']}/{item['pr_repo']}`)")
                st.caption(f"ID: `{item['id']}` | Date: `{item['created_at']}`")
            with col_h2:
                if st.button("View", key=f"btn_view_{item['id']}"):
                    loaded = get_investigation(item["id"])
                    if loaded:
                        st.session_state["current_result"] = loaded
                        st.rerun()
            st.divider()

