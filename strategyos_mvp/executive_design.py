from __future__ import annotations

from copy import deepcopy
import re
from typing import Any


EXECUTIVE_DESIGN: dict[str, Any] = {
    "personas": {
        "ceo": {
            "health": {"score": 78, "headline": "Broadly on track — margin needs attention.", "body": "Revenue is ahead of plan, but margin is leaking to FX and API cost, and two business units are dragging. Two decisions are due before Thursday’s board.", "scoreNote": "plan health"},
            "indexLabel": "The group index",
            "assistant": "Hermes",
            "assistantRole": "chief of staff",
            "brief": "The Group CEO lane should feel like the 22.06 authority: group altitude first, board-safe narrative second, and no Oracle-pilot override copy in the anchor surface. Twin-platform history remains visible as delivery history, Oracle-backed finance rings now drive the CEO surface in the pilot record, Oracle-backed · deterministic copy remains preserved in the pilot history, and manual / deferred operational context stays explicit rather than disguised.",
            "quote": "Margin needs attention, but the room should stay grounded in what moved the number and what decisions are due before Thursday.",
            "by": "Hermes · Group CEO chief of staff",
            "threads": [{"key": "briefing", "title": "Thursday board readiness", "preview": "Am I on track for the board on Thursday?"}, {"key": "hedge", "title": "What 60% EUR hedge saves", "preview": "Model a 60% EUR hedge — what does it save?"}, {"key": "recognition", "title": "e-Pharmacy capacity pull-forward", "preview": "Should we pull forward e-Pharmacy fulfilment capacity?"}],
            "prompts": ["Why is the gap widening?", "Show e-Pharmacy detail.", "Risk to full-year plan?"],
            "drivers": [
                {"key": "revenue", "label": "Revenue", "pct": 102, "value": "SAR 2.09B", "sub": "quarter to date", "vsPlan": "+2.3% vs plan", "story": "102% of plan and climbing — the gap to plan has widened in your favour across the quarter. Lifted by e-Pharmacy and Retail; Healthcare is the only line below.", "movers": {"lifting": [{"name": "e-Pharmacy", "delta": "+12% orders WoW", "contribution": 38}, {"name": "Pharmacy Retail", "delta": "+8.3% like-for-like", "contribution": 27}, {"name": "Digital Health", "delta": "+36% revenue YoY", "contribution": 15}], "dragging": [{"name": "Healthcare Services", "delta": "−3.8% occupancy", "contribution": -18}, {"name": "Tamween Distribution", "delta": "+0.4% — flat vs plan", "contribution": -6}]}, "chips": ["Why is the gap widening?", "Show e-Pharmacy detail", "Risk to full-year plan?"]},
                {"key": "ebitda", "label": "EBITDA margin", "pct": 99, "value": "19.2%", "sub": "vs 19.4% plan", "vsPlan": "−20 bps vs plan", "story": "99% of plan — margin is the soft spot. FX and API input cost are the leak; two dragging BUs explain most of the rest. A hedge decision is on Thursday’s board agenda.", "movers": {"lifting": [{"name": "Manufacturing", "delta": "+60 bps on yield", "contribution": 22}, {"name": "Pharmacy Retail", "delta": "+30 bps mix", "contribution": 12}], "dragging": [{"name": "FX exposure", "delta": "~SAR 9k / wk drag", "contribution": -20}, {"name": "Tamween Distribution", "delta": "leakage · SAR 1.2M", "contribution": -16}, {"name": "API input cost", "delta": "+4.1% vs plan", "contribution": -11}]}, "chips": ["What would a 60% EUR hedge save?", "Show the FX bridge", "Which BUs can offset?"]},
                {"key": "digital_health", "label": "Digital Health revenue", "pct": 100, "value": "SAR 186M", "sub": "flat by EOY scenario", "vsPlan": "flat vs plan", "story": "Digital Health is flattening into year-end unless adoption picks up; the board needs to decide whether to treat it as a hold or fund a sharper commercial push.", "movers": {"lifting": [{"name": "Virtual chronic care", "delta": "+3% enrolments"}], "dragging": [{"name": "Enterprise EHR deals", "delta": "slower conversion"}]}},
                {"key": "healthcare", "label": "Healthcare occupancy", "pct": 96, "value": "81% occupancy", "sub": "below target", "vsPlan": "−3.8% vs plan", "story": "Healthcare occupancy is the only major operating drag in the CEO view; recovery depends on clearing staffing gaps before the variance turns structural.", "movers": {"lifting": [{"name": "Locum cover", "delta": "next week"}], "dragging": [{"name": "Cardiology occupancy", "delta": "below plan"}]}}
            ],
            "findings": [{"title": "FX is building a ~SAR 9k margin drag this week", "tag": "Group KPI · EBITDA margin", "detail": "EUR/SAR drift against an unhedged slice of API purchasing. A 60% hedge neutralises most of it; decision sits on Thursday’s board agenda.", "tone": "flat"}, {"title": "SAR 8.6M is recoverable across the group", "tag": "Cross-BU finding", "detail": "Tamween audit (SAR 1.2M), duplicate-vendor spend, and aged AR concentrate the opportunity. The system has drafted the recovery sequence.", "tone": "flat"}, {"title": "Operational resilience intact — cold-chain at a record", "tag": "Group KPI · Resilience · run by Logistics", "detail": "Cold-chain integrity reached 99.4%, the best on record, through the summer peak. No excursions in the last 30 days.", "tone": "up"}],
            "developments": [{"title": "Cold-chain hit a record 99.4% — best ever", "meta": "Pharma Logistics · 2h ago", "impact": "Reinforces the Resilience KPI and de-risks the NUPCO ramp. No plan change — protect the practice.", "kind": "win"}, {"title": "NUPCO Q1 awards confirmed: +SAR 145M annual", "meta": "Capital · 5h ago", "impact": "Lifts the full-year revenue bridge by ~SAR 145M and improves cash timing. Plan revised upward next cycle.", "kind": "win"}, {"title": "Tamween audit: SAR 1.2M recoverable", "meta": "Tamween Distribution · yesterday", "impact": "Folds into the SAR 8.6M group recovery. Net margin uplift ~10 bps once collected.", "kind": "watch"}],
            "week": [{"key": "board_prep", "day": "Thu", "title": "Board meeting", "when": "in 3 days", "prep": "Two decisions open: the FX hedge and the GLP-1 JV. The pack is 80% composed — margin narrative needs your line.", "urgent": True, "prompt": "Am I on track for the board on Thursday?"}, {"key": "jv", "day": "Wed", "title": "GLP-1 JV signature", "when": "in 2 days", "prep": "Supply-lock terms agreed; cash headroom confirmed. e-Pharmacy demand model attached.", "urgent": True, "prompt": "Can we fund the JV from cash?"}, {"key": "call", "day": "Tue", "title": "e-Pharmacy GM — opportunity call", "when": "tomorrow", "prep": "Lina wants to pull forward fulfilment capacity. Bring the 12% WoW order curve.", "urgent": False, "prompt": "Should we pull forward e-Pharmacy fulfilment capacity?"}, {"key": "regulator", "day": "next Fri", "title": "Regulator meeting", "when": "in 1 week", "prep": "Routine cold-chain review — the 99.4% record is your opening.", "urgent": False, "prompt": "What should I emphasise in the regulator meeting?"}],
        },
        "cfo": {
            "health": {"score": 74, "headline": "Oracle-first CFO surface is live.", "body": "The CFO story now starts with Oracle finance ingestion, deterministic KPI outputs, leakage review, and explicit manual-input controls. Generic twin framing is demoted to delivery history.", "scoreNote": "oracle pilot posture"},
            "indexLabel": "The financial index",
            "assistant": "Atlas",
            "assistantRole": "finance chief of staff",
        "brief": "This is now an Oracle-first CFO surface: liquidity stays strong, deterministic pilot math comes first, explicit reconciliation and leakage context come second, and no fake automation sits beyond finance scope.",
            "quote": "If a number cannot be traced to Oracle finance or an approved manual input, it does not belong in the CFO pilot surface as automation.",
            "by": "Atlas · Group CFO chief of staff",
            "threads": [{"key": "briefing", "title": "EBITDA bridge for the pack", "preview": "Walk me through the EBITDA bridge."}, {"key": "hedge", "title": "SAR 8.6M recovery sequence", "preview": "Where is the SAR 8.6M and how fast can we get it?"}, {"key": "recognition", "title": "JV funding", "preview": "Can the JV be funded from cash?"}],
            "prompts": ["Walk me through the EBITDA bridge.", "Where is the SAR 8.6M?", "Can the JV be funded from cash?"],
            "drivers": [{"key": "revq", "label": "Revenue quality", "pct": 101, "value": "SAR 2.09B", "sub": "94% recurring", "vsPlan": "+2.3% vs plan", "story": "Revenue is ahead and the mix is healthy — 94% recurring, low concentration. NUPCO awards improve quality further next cycle.", "movers": {"lifting": [{"name": "NUPCO contracts", "delta": "+SAR 145M annual", "contribution": 30}, {"name": "e-Pharmacy recurring", "delta": "+12% refill base", "contribution": 20}], "dragging": [{"name": "Healthcare one-offs", "delta": "lower elective mix", "contribution": -10}]}}, {"key": "bridge", "label": "EBITDA bridge", "pct": 99, "value": "19.2%", "sub": "vs 19.4% plan", "vsPlan": "−20 bps vs plan", "story": "Volume and price add; FX and API cost subtract. The net is a 20 bps miss — a 60% EUR hedge recovers ~15 bps of it.", "movers": {"lifting": [{"name": "Volume", "delta": "+40 bps", "contribution": 24}, {"name": "Price / mix", "delta": "+25 bps", "contribution": 14}], "dragging": [{"name": "FX", "delta": "−35 bps", "contribution": -22}, {"name": "API cost", "delta": "−30 bps", "contribution": -16}]}}, {"key": "wc", "label": "Working capital", "pct": 96, "value": "58 days", "sub": "cash conversion cycle", "vsPlan": "+3 days vs plan", "story": "DSO 47, DPO 41, DIO 52. The cycle is 3 days long, concentrated in inventory build for the JV.", "movers": {"lifting": [{"name": "DPO discipline", "delta": "+4 days", "contribution": 16}], "dragging": [{"name": "DIO — GLP-1 stock", "delta": "+6 days", "contribution": -14}, {"name": "DSO — NUPCO terms", "delta": "+2 days", "contribution": -6}]}}, {"key": "liq", "label": "Liquidity & covenant", "pct": 123, "value": "SAR 1.48B", "sub": "Net debt/EBITDA 1.6x", "vsPlan": "2.6x covenant", "story": "Cash is 123% of floor; leverage is 1.6x against a 2.6x covenant — a full turn of headroom.", "movers": {"lifting": [{"name": "Collections", "delta": "+SAR 145M", "contribution": 28}, {"name": "Rate relief", "delta": "~SAR 5M/yr", "contribution": 10}], "dragging": [{"name": "JV pre-funding", "delta": "SAR 60M", "contribution": -8}]}}],
            "cashPulse": {"title": "Cash Pulse", "note": "four pillars", "pillars": [{"label": "Cash in", "value": "SAR 612M", "sub": "collections", "delta": "+SAR 145M NUPCO", "tone": "up"}, {"label": "Cash out", "value": "SAR 534M", "sub": "disbursed", "delta": "DPO +4 days", "tone": "flat"}, {"label": "At bank", "value": "SAR 1.48B", "sub": "available liquidity", "delta": "+SAR 60M wk", "tone": "up"}, {"label": "Lost / leaking", "value": "SAR 8.6M", "sub": "recoverable group-wide", "delta": "invoke leakage scan", "tone": "down"}]},
            "findings": [{"title": "FX is building a ~SAR 9k margin drag this week", "tag": "Group KPI · EBITDA bridge", "detail": "Unhedged EUR slice of API purchasing. A 60% hedge neutralises most of it — board decision Thursday.", "tone": "flat"}, {"title": "SAR 8.6M is recoverable — leakage scan ready", "tag": "Cross-BU finding · Cash-Leakage add-on", "detail": "Tamween audit, duplicate-vendor spend, aged AR. One tap opens the drafted recovery sequence.", "tone": "down"}, {"title": "Covenant headroom at a full turn (1.6x vs 2.6x)", "tag": "Group KPI · Liquidity", "detail": "Leverage stays well inside covenant; rate easing adds ~SAR 5M/yr.", "tone": "up"}],
            "developments": [{"title": "NUPCO Q1 awards confirmed: +SAR 145M annual", "meta": "Capital · 5h ago", "impact": "Improves cash timing and revenue quality.", "kind": "win"}, {"title": "Tamween audit: SAR 1.2M recoverable", "meta": "Tamween Distribution · yesterday", "impact": "Folds into the SAR 8.6M recovery.", "kind": "watch"}, {"title": "Rates eased — ~SAR 5M/yr interest relief", "meta": "Treasury · today", "impact": "Supports the JV funding case from cash.", "kind": "win"}],
            "week": [{"key": "board_meeting", "day": "Thu", "title": "Board meeting", "when": "in 3 days", "prep": "Own the margin and hedge narrative. The EBITDA bridge and covenant slide are composed; confirm the hedge ratio.", "urgent": True, "prompt": "Walk me through the EBITDA bridge."}, {"key": "jv_funding", "day": "Wed", "title": "GLP-1 JV funding sign-off", "when": "in 2 days", "prep": "Fund from cash vs facility — the cash case is cheaper post rate relief.", "urgent": True, "prompt": "Can the JV be funded from cash?"}, {"key": "treasury", "day": "Tue", "title": "Treasury hedge execution", "when": "tomorrow", "prep": "Pre-clear the 60% EUR hedge so it can execute the moment the board approves.", "urgent": False, "prompt": "Model the 60% hedge."}],
        },
        "gm": {
            "health": {"score": 84, "headline": "Strong week — capacity is the constraint.", "body": "Demand is healthy; capacity and SLA discipline decide whether the week stays beautiful or breaks.", "scoreNote": "plan health"},
            "assistant": "Iris",
            "assistantRole": "ground operator",
            "brief": "The growth line is strong; the operating question is whether capacity can keep up without sacrificing service quality.",
            "quote": "Demand is healthy — capacity and service discipline decide the week.",
            "by": "Iris · BU GM chief of staff",
            "threads": [{"key": "hub", "title": "Eastern hub bottleneck", "preview": "How long until the Eastern hub caps us?"}, {"key": "capacity", "title": "Capacity bind", "preview": "Where is capacity binding first?"}, {"key": "ceo", "title": "Opportunity call", "preview": "What do I owe the CEO before tomorrow's call?"}],
            "prompts": ["How long until the Eastern hub caps us?", "Where is capacity binding first?", "What do I owe the CEO before tomorrow's call?"],
            "drivers": [{"key": "revenue", "label": "Unit revenue", "pct": 112, "value": "SAR 214M", "sub": "quarter to date", "vsPlan": "+12% vs plan", "story": "Revenue is compounding on the refill cohort, but capacity binds first in the Eastern hub.", "movers": {"lifting": [{"name": "Riyadh region", "delta": "+18% orders"}], "dragging": [{"name": "Eastern region", "delta": "capacity-capped"}]}}, {"key": "capacity", "label": "Capacity posture", "pct": 94, "value": "94% utilisation", "sub": "Eastern hub", "vsPlan": "binding soon", "story": "Capacity is the first operational ceiling and determines whether service holds through peak.", "movers": {"lifting": [{"name": "Automation line", "delta": "ready to pull forward"}], "dragging": [{"name": "Eastern hub", "delta": "binds in 2 weeks"}]}}, {"key": "sla", "label": "Fulfilment SLA", "pct": 100, "value": "96.5% on-time", "sub": "2.0 days", "vsPlan": "on plan", "story": "SLA and fulfilment quality are holding, but they will slip if the hub bind is ignored.", "movers": {"lifting": [{"name": "Route density", "delta": "stable"}], "dragging": [{"name": "Eastern surge", "delta": "service risk"}]}}, {"key": "cost", "label": "Cost to serve", "pct": 98, "value": "SAR 38/order", "sub": "below plan", "vsPlan": "−2% vs plan", "story": "Cost to serve remains disciplined while the capacity issue is managed.", "movers": {"lifting": [{"name": "Warehouse automation", "delta": "lower touch time"}], "dragging": [{"name": "Surge routing", "delta": "+8% in East"}]}}],
            "findings": [{"title": "Refill cohort is compounding", "tag": "Revenue", "detail": "+12% WoW and capacity is the only ceiling.", "tone": "up"}, {"title": "Eastern region capacity binds within 2 weeks", "tag": "Fulfilment", "detail": "Shift volume or pull forward automation.", "tone": "flat"}],
            "developments": [{"title": "App conversion hit a new high", "meta": "Digital · today", "impact": "Supports the revenue beat.", "kind": "win"}],
            "week": [{"key": "ceo", "day": "Tue", "title": "Opportunity call with the CEO", "when": "tomorrow", "prep": "Bring the 12% WoW curve and the Eastern bottleneck.", "urgent": True, "prompt": "What do I owe the CEO before tomorrow's call?"}, {"key": "capacity", "day": "Wed", "title": "Capacity decision", "when": "in 2 days", "prep": "Pull forward the automation line if needed.", "urgent": True, "prompt": "Where is capacity binding first?"}, {"key": "hub", "day": "Fri", "title": "Hub readiness", "when": "in 4 days", "prep": "Confirm how long until the Eastern hub caps out.", "urgent": False, "prompt": "How long until the Eastern hub caps us?"}],
        },
        "bucfo": {
            "health": {"score": 66, "headline": "Margin recovering — leakage and cutover in flight.", "body": "Revenue is flat to plan while the SAR 1.2M leakage and S/4HANA cutover still need exact control.", "scoreNote": "plan health"},
            "assistant": "Argus",
            "assistantRole": "exacting controller",
            "brief": "Tamween's story is about exact control: leakage, DSO, and cutover recovery.",
            "quote": "The number improves only when the recovery sequence is real and the commentary rides up with it.",
            "by": "Argus · BU CFO chief of staff",
            "threads": [{"key": "variance", "title": "Variance note", "preview": "Draft my variance note on the margin drag."}, {"key": "recovery", "title": "Recovery path", "preview": "What is the SAR 1.2M recovery path?"}, {"key": "cutover", "title": "Cutover close", "preview": "What still needs closing before the cost line steps down?"}],
            "prompts": ["Draft my variance note on the margin drag.", "What is the SAR 1.2M recovery path?", "What still needs closing before the cost line steps down?"],
            "drivers": [{"key": "margin", "label": "Margin drag", "pct": 94, "value": "8.9%", "sub": "below plan", "vsPlan": "−60 bps vs plan", "story": "Margin is recovering, but leakage and dual-running cost still compress the line.", "movers": {"lifting": [{"name": "Freight renegotiation", "delta": "+20 bps"}], "dragging": [{"name": "Leakage", "delta": "SAR 1.2M"}]}}, {"key": "recovery", "label": "Recovery path", "pct": 88, "value": "SAR 1.2M", "sub": "audit-confirmed", "vsPlan": "in progress", "story": "The SAR 1.2M recovery path is sequenced across institutional AR and duplicate-vendor lines.", "movers": {"lifting": [{"name": "Collections plan", "delta": "drafted"}], "dragging": [{"name": "Aged AR", "delta": ">90 days"}]}}, {"key": "cutover", "label": "Cutover close", "pct": 92, "value": "+30 bps cost", "sub": "dual running", "vsPlan": "temporary", "story": "S/4HANA cutover still carries temporary dual-running cost until the legacy retirement date is locked.", "movers": {"lifting": [{"name": "UAT passed", "delta": "ready for go-live"}], "dragging": [{"name": "Legacy overlap", "delta": "+30 bps"}]}}, {"key": "dso", "label": "Collections discipline", "pct": 95, "value": "91 days", "sub": "institutional account watch", "vsPlan": "+5 days vs plan", "story": "Collections discipline remains the cleanest way to accelerate the margin recovery commentary.", "movers": {"lifting": [{"name": "Payment-plan options", "delta": "prepared"}], "dragging": [{"name": "Institutional A", "delta": "past 90 days"}]}}],
            "findings": [{"title": "SAR 1.2M leakage confirmed by audit", "tag": "Margin", "detail": "Recovery sequence is drafted.", "tone": "down"}, {"title": "Cutover dual-running adds cost", "tag": "Operating cost", "detail": "Temporary while legacy remains active.", "tone": "flat"}],
            "developments": [{"title": "S/4HANA cutover passed UAT", "meta": "Transformation · yesterday", "impact": "Cost relief comes after legacy retirement.", "kind": "win"}],
            "week": [{"key": "note", "day": "Mon", "title": "Variance note to Group CFO", "when": "due today", "prep": "Confirm the SAR 1.2M recovery path.", "urgent": True, "prompt": "Draft my variance note on the margin drag."}, {"key": "collections", "day": "Tue", "title": "Collections call", "when": "tomorrow", "prep": "Bring aged-AR payment-plan options.", "urgent": True, "prompt": "What is the SAR 1.2M recovery path?"}, {"key": "cutover", "day": "Thu", "title": "Cutover go-live review", "when": "in 3 days", "prep": "Lock the legacy retirement date.", "urgent": False, "prompt": "What still needs closing before the cost line steps down?"}],
        },
        "logistics": {
            "health": {"score": 80, "headline": "Resilience is carrying confidence.", "body": "Cold-chain reliability is the quiet strength in the packet.", "scoreNote": "resilience"},
            "assistant": "Vega",
            "assistantRole": "logistics chief of staff",
            "brief": "Cold-chain and service reliability remain the calm strength in the packet.",
            "quote": "Cold-chain credibility lets the board focus on strategy instead of firefighting.",
            "by": "Vega · logistics chief of staff",
            "threads": [{"key": "service", "title": "Cold-chain watch", "preview": "What keeps service credibility strongest this week?"}, {"key": "continuity", "title": "Continuity risk", "preview": "Where could continuity slip before the board?"}, {"key": "win", "title": "Operational win", "preview": "Which logistics win should the board hear?"}],
            "prompts": ["What keeps service credibility strongest this week?", "Where could continuity slip before the board?", "Which logistics win should the board hear?"],
            "drivers": [{"key": "service", "label": "Service credibility", "pct": 101, "value": "96.5% on-time", "sub": "continuity and delivery", "vsPlan": "+1 pt vs plan", "story": "Service credibility remains strong because continuity stayed boring and precise.", "movers": {"lifting": [{"name": "Riyadh hub", "delta": "steady flow"}], "dragging": [{"name": "Eastern surge", "delta": "capacity pressure"}]}}, {"key": "coldchain", "label": "Cold-chain integrity", "pct": 99, "value": "99.4%", "sub": "record week", "vsPlan": "record", "story": "Cold-chain integrity is the logistics proof point the board should hear.", "movers": {"lifting": [{"name": "Summer peak control", "delta": "no excursions"}], "dragging": [{"name": "Eastern alert", "delta": "cleared"}]}}, {"key": "cost", "label": "Cost to serve", "pct": 98, "value": "SAR 38/order", "sub": "within tolerance", "vsPlan": "on plan", "story": "Fuel pressure is visible, but cost discipline has not broken the resilience story.", "movers": {"lifting": [{"name": "Route density", "delta": "−5%"}], "dragging": [{"name": "Fuel", "delta": "+2.6% vs plan"}]}}, {"key": "readiness", "label": "Board readiness", "pct": 101, "value": "room confidence", "sub": "operations story clear", "vsPlan": "board-safe", "story": "Operations should arrive in the room as proof and reassurance, not as a scramble.", "movers": {"lifting": [{"name": "Recognition drafted", "delta": "ready"}], "dragging": [{"name": "Continuity slip risk", "delta": "watch East"}]}}],
            "findings": [{"title": "Cold-chain hit 99.4% — best ever", "tag": "Resilience", "detail": "No excursions in the last 30 days.", "tone": "up"}, {"title": "Eastern region surge remains the one service risk", "tag": "Capacity", "detail": "Extra load needs careful orchestration before it shows in the board packet.", "tone": "flat"}],
            "developments": [{"title": "Recognition drafted for the Logistics GM", "meta": "Hermes + Vega · today", "impact": "Ready to ride upward into the weekly note.", "kind": "win"}],
            "week": [{"key": "continuity", "day": "Tue", "title": "Continuity review", "when": "tomorrow", "prep": "Re-check the Eastern hub and route assumptions.", "urgent": True, "prompt": "Where could continuity slip before the board?"}, {"key": "board", "day": "Thu", "title": "Board note", "when": "in 3 days", "prep": "Carry the cold-chain record into the board narrative.", "urgent": False, "prompt": "Which logistics win should the board hear?"}, {"key": "service", "day": "Fri", "title": "Service review", "when": "in 4 days", "prep": "Keep service credibility explicit.", "urgent": False, "prompt": "What keeps service credibility strongest this week?"}],
        },
    },
    "board": {"assistant": "Minerva", "meeting": {"title": "Q2 Board Meeting", "when": "in 3 days", "date": "Thu 18 Jun · 14:00", "room": "Riyadh HQ + remote"}, "governance": "Nothing reaches the board until the Group CEO approves it.", "kpis": [{"key": "revenue", "label": "Revenue", "pct": 102, "value": "SAR 2.09B", "sub": "quarter to date"}, {"key": "ebitda", "label": "EBITDA margin", "pct": 99, "value": "19.2%", "sub": "vs 19.4% plan"}, {"key": "cash", "label": "Cash vs floor", "pct": 123, "value": "SAR 1.48B", "sub": "vs SAR 1.2B floor"}, {"key": "localisation", "label": "Vision 2030 localisation", "pct": 104, "value": "38.4% Saudization", "sub": "vs 37% target"}], "decks": [{"title": "Group performance & plan health", "by": "Office of the CEO", "status": "approved", "pages": 14, "tag": "group KPI"}, {"title": "Margin & the FX hedge decision", "by": "Group CFO · Atlas", "status": "approved", "pages": 9, "tag": "decision"}, {"title": "GLP-1 JV — supply lock & funding", "by": "e-Pharmacy + Capital", "status": "approved", "pages": 11, "tag": "decision"}, {"title": "Tamween recovery & cutover", "by": "BU CFO · Argus", "status": "pending CEO approval", "pages": 7, "tag": "rolled-up"}], "supplementary": [{"q": "What is the downside if EUR strengthens after a 60% hedge?", "to": "Group CEO", "status": "sent"}, {"q": "Can the JV be funded fully from cash without touching the facility?", "to": "Group CFO", "status": "answered"}], "livePrompts": ["Why is EBITDA 20 bps under plan?", "Show the hedge downside", "Is the JV funded from cash?"], "actions": [{"item": "Ratify the 60% EUR hedge", "owner": "Group CFO", "due": "on approval"}, {"item": "Approve GLP-1 JV signature", "owner": "Group CEO", "due": "this week"}, {"item": "Review Tamween recovery at Q3", "owner": "Audit committee", "due": "Q3"}], "summary": "Board endorsed the margin-protection plan and ratified the hedge; approved the GLP-1 JV subject to final supply terms. Recovery of SAR 8.6M will be reviewed at Q3."},
    "activity": {"line": "5 agents · 25 steps · 15 tool calls — recovered SAR 8.6M of leakage and composed 80% of the board pack", "metrics": [{"k": "agents", "v": "5"}, {"k": "steps", "v": "25"}, {"k": "tool calls", "v": "15"}, {"k": "value found", "v": "SAR 8.6M"}], "log": [{"t": "06:14", "who": "Hermes", "a": "Engaged board-pack composition."}, {"t": "06:05", "who": "Leakage scan", "a": "Recovered SAR 1.2M at Tamween and rolled it into SAR 8.6M group recovery."}]},
    "runningAgents": [{"id": "boardpack", "name": "Board pack composer", "by": "Office of the CEO", "status": "running", "progress": 80, "tag": "board prep", "doing": "Drafting the margin narrative."}, {"id": "leakage", "name": "Leakage recovery scan", "by": "Group CFO", "status": "running", "progress": 38, "tag": "cash · governance", "doing": "Scanning for recoverable spend."}, {"id": "hedge", "name": "FX hedge pre-clearance", "by": "Treasury", "status": "approval", "progress": 100, "tag": "EBITDA", "doing": "A 60% EUR hedge is staged pending approval."}, {"id": "variance", "name": "Variance commentary collector", "by": "Group CFO", "status": "running", "progress": 75, "tag": "rolled-up", "doing": "Gathering BU commentary."}, {"id": "coldchain", "name": "Cold-chain integrity monitor", "by": "Pharma Logistics", "status": "standing", "progress": 91, "tag": "resilience", "doing": "Watching continuity and recognition-ready proof points."}],
    "discoverAgents": [{"id": "covenant", "glyph": "⚖", "name": "Covenant sentinel", "source": "native", "by": "StrategyOS", "desc": "Watches leverage against every covenant.", "connector": "Treasury · loan agreements"}, {"id": "workingcap", "glyph": "◴", "name": "Working-capital optimiser", "source": "native", "by": "StrategyOS", "desc": "Models DSO / DPO / DIO moves.", "connector": "S/4HANA · AR / AP"}, {"id": "scenario", "glyph": "◇", "name": "Scenario planner", "source": "native", "by": "StrategyOS", "desc": "Runs multi-driver what-ifs with no side effects.", "connector": "knowledge graph"}, {"id": "supplier", "glyph": "⬡", "name": "Supplier-risk monitor", "source": "market", "by": "ChainLens", "desc": "Tracks API supplier disruption and lead times.", "connector": "supplier EDI"}],
    "subtools": [{"name": "Spreadsheet", "glyph": "▦", "desc": "Builds and audits models."}, {"name": "Document & PDF", "glyph": "▤", "desc": "Reads decks and contracts."}, {"name": "Calls at scale", "glyph": "☏", "desc": "Runs structured outreach."}, {"name": "Marketing content", "glyph": "✎", "desc": "Drafts recognition notes on-brand."}],
}


def executive_persona_design(persona_id: str) -> dict[str, Any]:
    personas = EXECUTIVE_DESIGN.get("personas") or {}
    return deepcopy(personas.get(persona_id) or personas.get("ceo") or {})


def executive_board_design() -> dict[str, Any]:
    return deepcopy(EXECUTIVE_DESIGN.get("board") or {})


def executive_activity_design() -> dict[str, Any]:
    return deepcopy(EXECUTIVE_DESIGN.get("activity") or {})


def executive_running_agents_design() -> list[dict[str, Any]]:
    return deepcopy(list(EXECUTIVE_DESIGN.get("runningAgents") or []))


def executive_discover_agents_design() -> list[dict[str, Any]]:
    return deepcopy(list(EXECUTIVE_DESIGN.get("discoverAgents") or []))


def executive_subtools_design() -> list[dict[str, Any]]:
    return deepcopy(list(EXECUTIVE_DESIGN.get("subtools") or []))


def _extract_money_to_sar(text: str, default: float = 0.0) -> float:
    match = re.search(r"SAR\s+([0-9]+(?:\.[0-9]+)?)\s*([MB]?)", str(text or ""), re.IGNORECASE)
    if not match:
        return default
    value = float(match.group(1))
    suffix = match.group(2).upper()
    if suffix == "M":
        return value * 1_000_000
    if suffix == "B":
        return value * 1_000_000_000
    return value


def executive_public_assistant_packet(persona_id: str = "ceo") -> dict[str, Any]:
    persona = executive_persona_design(persona_id)
    board = executive_board_design()
    activity = executive_activity_design()
    running_agents = executive_running_agents_design()
    findings = list(persona.get("findings") or [])
    developments = list(persona.get("developments") or [])
    week = list(persona.get("week") or [])
    drivers = list(persona.get("drivers") or [])
    kpis = list(board.get("kpis") or [])
    public_facts = {
        "group_recoverable_sar": 8_600_000.0,
        "tamween_recoverable_sar": 1_200_000.0,
        "fx_drag_weekly_sar": 9_000.0,
        "fx_hedge_recovery_bps": 15.0,
        "ebitda_margin_pct": 19.2,
        "ebitda_plan_pct": 19.4,
        "epharmacy_orders_wow_pct": 12.0,
        "healthcare_occupancy_delta_pct": -3.8,
        "board_pack_completion_pct": 80.0,
        "cold_chain_integrity_pct": 99.4,
        "nupco_award_sar": 145_000_000.0,
        "source_boundary": "Public-safe executive packet only; reviewer evidence documents remain on the protected surface.",
    }
    facts_by_persona = {
        "ceo": [
            "Tamween audit: SAR 1.2M recoverable.",
            "SAR 8.6M is recoverable across the group.",
            "e-Pharmacy orders are +12% week on week and fulfilment is holding at a 2-day SLA.",
            "FX is building a ~SAR 9k weekly drag on EBITDA margin and a 60% EUR hedge recovers most of it.",
            "Healthcare Services occupancy is −3.8% below plan and remains the main operating drag.",
            "The board pack is 80% composed and the board prep still needs the margin narrative.",
        ],
        "cfo": [
            "SAR 8.6M is recoverable across the group and the leakage scan is ready.",
            "Tamween contributes SAR 1.2M into that recovery pool.",
            "EBITDA margin is 19.2% versus 19.4% plan; a 60% EUR hedge recovers roughly 15 bps.",
            "Cash is SAR 1.48B with 1.6x leverage against a 2.6x covenant.",
            "Rates easing adds roughly SAR 5M per year of relief and supports the JV funding case from cash.",
        ],
        "gm": [
            "e-Pharmacy revenue is SAR 214M, +12% versus plan.",
            "Orders are +12% week on week on the refill cohort.",
            "Capacity binds first in the Eastern hub at 94% utilisation and within roughly 2 weeks.",
            "Fulfilment is still holding a 2-day SLA, so the visible constraint is capacity rather than demand.",
        ],
        "bucfo": [
            "Tamween has SAR 1.2M audit-confirmed recoverable value.",
            "Margin is 8.9%, 60 bps below plan, with leakage and cutover dual-running cost as the drag.",
            "The recovery path is sequenced across institutional AR and duplicate-vendor lines.",
            "DSO is 91 days, 5 days above plan, and collections discipline is the cleanest acceleration lever.",
        ],
        "logistics": [
            "Cold-chain integrity is 99.4%, the best on record.",
            "Eastern surge remains the main service risk.",
            "Service credibility is 96.5% on-time and the board should hear the resilience proof points.",
        ],
    }
    facts = list(facts_by_persona.get(persona_id) or facts_by_persona["ceo"])
    return {
        "packet_id": f"public-executive:{persona_id}",
        "persona_id": persona_id,
        "assistant": persona.get("assistant") or "Hermes",
        "health": persona.get("health") or {},
        "kpis": kpis,
        "drivers": drivers,
        "findings": findings,
        "developments": developments,
        "week": week,
        "board_portal": board,
        "activity": activity,
        "running_agents": running_agents,
        "public_facts": public_facts,
        "facts": facts,
        "kg_nodes": [
            {"id": "kpi:revenue", "label": "Revenue", "properties": {"value": "SAR 2.09B", "vs_plan": "+2.3%"}},
            {"id": "kpi:ebitda", "label": "EBITDA margin", "properties": {"value": "19.2%", "vs_plan": "−20 bps"}},
            {"id": "initiative:epharmacy", "label": "e-Pharmacy", "properties": {"orders_wow_pct": 12}},
            {"id": "finding:tamween", "label": "Tamween audit", "properties": {"recoverable_sar": 1_200_000}},
            {"id": "finding:group_recovery", "label": "Group recovery", "properties": {"recoverable_sar": 8_600_000}},
            {"id": "risk:fx", "label": "FX exposure", "properties": {"weekly_drag_sar": 9_000, "hedge_recovery_bps": 15}},
            {"id": "board:meeting", "label": "Board meeting", "properties": {"pack_completion_pct": 80}},
        ],
        "kg_edges": [
            {"source": "initiative:epharmacy", "target": "kpi:revenue", "label": "LIFTS"},
            {"source": "risk:fx", "target": "kpi:ebitda", "label": "DRAGS"},
            {"source": "finding:tamween", "target": "finding:group_recovery", "label": "PART_OF"},
            {"source": "finding:group_recovery", "target": "board:meeting", "label": "BOARD_TOPIC"},
        ],
        "trace_summary": {
            "activity_line": activity.get("line"),
            "running_agent_count": len(running_agents),
            "finding_count": len(findings),
            "development_count": len(developments),
        },
    }


PUBLIC_ASSISTANT_CONTEXT_PACKET: dict[str, Any] = {
    "packet_id": "public-executive-context:v1",
    "source": "executive_public_packet",
    "source_label": "StrategyOS public executive packet",
    "public_safe": True,
    "kpis": [
        {"key": "revenue", "label": "Revenue", "value": "SAR 2.09B", "vs_plan": "+2.3% vs plan", "story": "Revenue is ahead of plan, led by e-Pharmacy and Retail while Healthcare is below plan."},
        {"key": "ebitda", "label": "EBITDA margin", "value": "19.2%", "vs_plan": "−20 bps vs plan", "story": "Margin is the soft spot, with FX and API input cost as the main drag."},
        {"key": "cash", "label": "Cash vs floor", "value": "SAR 1.48B", "vs_plan": "+SAR 280M above floor", "story": "Liquidity remains strong and preserves headroom for the GLP-1 JV."},
    ],
    "drivers": [
        {
            "key": "revenue",
            "label": "Revenue",
            "value": "SAR 2.09B",
            "vs_plan": "+2.3% vs plan",
            "story": "The gap to plan has widened in the group's favour across the quarter.",
            "lifting": [
                {"name": "e-Pharmacy", "delta": "+12% orders WoW", "contribution": 38, "detail": "GLP-1 refill cohort is compounding and fulfilment is holding at a 2-day SLA."},
                {"name": "Pharmacy Retail", "delta": "+8.3% like-for-like", "contribution": 27},
                {"name": "Digital Health", "delta": "+36% revenue YoY", "contribution": 15},
            ],
            "dragging": [
                {"name": "Healthcare Services", "delta": "−3.8% occupancy", "contribution": -18, "detail": "Two consultants are on leave; locum cover lands next week."},
                {"name": "Tamween Distribution", "delta": "+0.4% — flat vs plan", "contribution": -6, "detail": "Recovering SAR 1.2M leakage while targeting 9.5% margin by year-end."},
            ],
        },
        {
            "key": "ebitda",
            "label": "EBITDA margin",
            "value": "19.2%",
            "vs_plan": "−20 bps vs plan",
            "story": "FX exposure and API input cost are the main leaks; a 60% EUR hedge is on Thursday's board agenda.",
            "lifting": [
                {"name": "Manufacturing", "delta": "+60 bps on yield", "contribution": 22},
                {"name": "Pharmacy Retail", "delta": "+30 bps mix", "contribution": 12},
            ],
            "dragging": [
                {"name": "FX exposure", "delta": "~SAR 9k / wk drag", "contribution": -20, "detail": "A 60% EUR hedge neutralises most of the current drag and recovers ~15 bps."},
                {"name": "Tamween Distribution", "delta": "leakage · SAR 1.2M", "contribution": -16, "detail": "Recovering leakage and cutting cost via the S/4HANA cutover."},
                {"name": "API input cost", "delta": "+4.1% vs plan", "contribution": -11},
            ],
        },
    ],
    "findings": [
        {
            "finding_id": "public-fx-drag",
            "title": "FX is building a ~SAR 9k margin drag this week",
            "pattern_type": "fx_hedge_unapplied",
            "detail": "EUR/SAR drift against an unhedged slice of API purchasing. A 60% hedge neutralises most of it; decision sits on Thursday's board agenda.",
            "recoverable_sar": 0.0,
            "domain": "ebitda_margin",
            "public_source": "executive_design",
        },
        {
            "finding_id": "public-group-recovery",
            "title": "SAR 8.6M is recoverable across the group",
            "pattern_type": "finance_leakage",
            "detail": "Tamween audit (SAR 1.2M), duplicate-vendor spend, and aged AR concentrate the opportunity. The system has drafted the recovery sequence.",
            "recoverable_sar": 8_600_000.0,
            "domain": "recovery",
            "public_source": "executive_design",
        },
        {
            "finding_id": "public-tamween-recovery",
            "title": "Tamween audit: SAR 1.2M recoverable",
            "pattern_type": "finance_leakage",
            "detail": "Folds into the SAR 8.6M group recovery. Net margin uplift is ~10 bps once collected.",
            "recoverable_sar": 1_200_000.0,
            "domain": "tamween_distribution",
            "public_source": "executive_design",
        },
        {
            "finding_id": "public-cold-chain",
            "title": "Operational resilience intact — cold-chain at a record",
            "pattern_type": "resilience",
            "detail": "Cold-chain integrity reached 99.4%, the best on record, through the summer peak.",
            "recoverable_sar": 0.0,
            "domain": "logistics",
            "public_source": "executive_design",
        },
    ],
    "developments": [
        {"title": "NUPCO Q1 awards confirmed: +SAR 145M annual", "impact": "Lifts the full-year revenue bridge by ~SAR 145M and improves cash timing."},
        {"title": "Tamween audit: SAR 1.2M recoverable", "impact": "Folds into the SAR 8.6M group recovery. Net margin uplift ~10 bps once collected."},
        {"title": "Cold-chain hit a record 99.4% — best ever", "impact": "Reinforces the resilience KPI and de-risks the NUPCO ramp."},
    ],
    "week": [
        {"key": "board_prep", "title": "Board meeting", "prep": "Two decisions open: the FX hedge and the GLP-1 JV. The pack is 80% composed — margin narrative needs your line.", "prompt": "Am I on track for the board on Thursday?"},
        {"key": "jv", "title": "GLP-1 JV signature", "prep": "Supply-lock terms agreed; cash headroom confirmed. e-Pharmacy demand model attached.", "prompt": "Can we fund the JV from cash?"},
        {"key": "call", "title": "e-Pharmacy GM — opportunity call", "prep": "Lina wants to pull forward fulfilment capacity. Bring the 12% WoW order curve.", "prompt": "Should we pull forward e-Pharmacy fulfilment capacity?"},
    ],
    "board_portal": {
        "summary": "Board endorsed the margin-protection plan and approved the GLP-1 JV subject to final supply terms.",
        "actions": [
            {"item": "Ratify the 60% EUR hedge", "owner": "Group CFO"},
            {"item": "Approve GLP-1 JV signature", "owner": "Group CEO"},
            {"item": "Review Tamween recovery at Q3", "owner": "Audit committee"},
        ],
    },
    "agent_activity": {
        "line": "5 agents · 25 steps · 15 tool calls — recovered SAR 8.6M of leakage and composed 80% of the board pack",
        "running_agents": [
            {"name": "Board pack composer", "progress": 80, "doing": "Drafting the margin narrative."},
            {"name": "Leakage recovery scan", "progress": 38, "doing": "Scanning for recoverable spend."},
            {"name": "FX hedge pre-clearance", "progress": 100, "doing": "A 60% EUR hedge is staged pending approval."},
        ],
    },
    "kg_nodes": [
        {"id": "finding:tamween", "label": "Tamween audit", "properties": {"domain": "tamween_distribution", "recoverable_sar": 1_200_000.0}},
        {"id": "finding:group-recovery", "label": "Group recovery", "properties": {"domain": "recovery", "recoverable_sar": 8_600_000.0}},
        {"id": "driver:epharmacy", "label": "e-Pharmacy", "properties": {"domain": "revenue", "detail": "+12% orders WoW"}},
        {"id": "driver:fx", "label": "FX exposure", "properties": {"domain": "ebitda_margin", "detail": "~SAR 9k / wk drag"}},
        {"id": "driver:healthcare", "label": "Healthcare Services", "properties": {"domain": "revenue", "detail": "−3.8% occupancy"}},
    ],
    "kg_edges": [
        {"source": "finding:tamween", "target": "finding:group-recovery", "label": "PART_OF"},
        {"source": "driver:epharmacy", "target": "driver:healthcare", "label": "OFFSETS"},
        {"source": "driver:fx", "target": "finding:group-recovery", "label": "BOARD_DECISION_CONTEXT"},
    ],
    "facts": [
        "Tamween audit: SAR 1.2M recoverable.",
        "SAR 8.6M is recoverable across the group.",
        "e-Pharmacy orders are +12% week on week and fulfilment is holding at a 2-day SLA.",
        "FX is building a ~SAR 9k weekly drag on EBITDA margin and a 60% EUR hedge recovers most of it.",
        "Healthcare Services occupancy is −3.8% below plan and remains the main operating drag.",
        "The board pack is 80% composed and the board prep still needs the margin narrative.",
    ],
}


def executive_public_assistant_context(persona_id: str = "ceo") -> dict[str, Any]:
    return executive_public_assistant_packet(persona_id)
