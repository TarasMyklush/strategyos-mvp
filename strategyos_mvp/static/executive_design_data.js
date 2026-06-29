(function () {
  window.STRATEGYOS_EXECUTIVE_DESIGN = {
    personas: {
      ceo: {
        health: {
          score: 78,
          headline: "Oracle-backed finance rings are live.",
          body: "The active CEO narrative is now the Oracle EBS pilot: deterministic finance metrics first, explicit manual inputs second, and operational context clearly marked manual / deferred.",
          scoreNote: "oracle pilot posture"
        },
        indexLabel: "The group index",
        assistant: "Hermes",
        assistantRole: "chief of staff",
        brief: "Oracle-backed finance metrics now drive the CEO surface. Twin-platform history remains visible, but the active narrative is Oracle pilot conformance.",
        quote: "Keep the CEO rings on deterministic Oracle finance outputs; everything else stays clearly labelled manual or deferred until it is truly sourced.",
        by: "Hermes · Group CEO chief of staff",
        secondaryMode: "hidden",
        threads: [
          { key: "briefing", title: "Thursday board readiness", preview: "Am I on track for the board on Thursday?" },
          { key: "hedge", title: "What 60% EUR hedge saves", preview: "Model a 60% EUR hedge — what does it save?" },
          { key: "recognition", title: "e-Pharmacy capacity pull-forward", preview: "Should we pull forward e-Pharmacy fulfilment capacity?" }
        ],
        prompts: [
          "What do the Oracle finance rings show?",
          "What is the single biggest Oracle pilot risk?",
          "Which context items are still manual / deferred?"
        ],
        drivers: [
          {
            key: "revenue",
            label: "Revenue",
              pct: 125,
              value: "125%",
              sub: "deterministic Oracle KPI",
              vsPlan: "Oracle-backed · deterministic",
              story: "This CEO ring now renders the deterministic Oracle revenue-attainment output directly. Completed twin-platform work stays in history, but the active board-safe surface starts from Oracle pilot finance truth.",
            trendLabel: "Weekly run-rate · 13 weeks",
            unit: "SAR M / wk",
              chips: ["Show Oracle source basis", "What manual inputs support this?", "Risk to publish posture?"],
              movers: {
                lifting: [
                  { name: "Oracle GL revenue facts", delta: "actual vs approved budget", contribution: 38, note: "Revenue attainment is calculated directly from Oracle GL revenue facts against the approved budget plan.", source_label: "oracle-backed" },
                  { name: "Budget plan baseline", delta: "approved manual input", contribution: 27, note: "Budget remains an explicit approved file input and is not disguised as Oracle automation.", source_label: "manual input" }
                ],
                dragging: [
                  { name: "Retail LfL", delta: "manual / deferred", contribution: -6, note: "Retail LfL remains visible as leadership context only. It is not part of the Oracle finance ring computation yet.", source_label: "manual / deferred" },
                  { name: "e-Rx demand pulse", delta: "manual / deferred", contribution: -4, note: "e-Rx demand remains a manual / deferred operating signal until a separate connector is delivered.", source_label: "manual / deferred" }
                ]
              }
          },
          {
            key: "ebitda",
            label: "EBITDA margin",
              pct: 125,
              value: "25.00%",
              sub: "deterministic Oracle KPI",
              vsPlan: "Oracle-backed · deterministic",
              story: "The CEO EBITDA ring is now the deterministic Oracle-backed output, not a generic twin-era margin placeholder. Narrative may follow, but the number is fixed first.",
            trendLabel: "Weekly EBITDA margin · 13 weeks",
            unit: "% margin",
              chips: ["Show the Oracle EBITDA bridge", "Which leakage findings matter?", "What remains manual?"],
              movers: {
                lifting: [
                  { name: "Oracle EBITDA output", delta: "25.00%", contribution: 22, note: "Computed directly from deterministic Oracle pilot math.", source_label: "oracle-backed" },
                  { name: "Leakage prioritisation", delta: "8 findings ranked", contribution: 12, note: "Leakage release sequence is attached to the finance evidence pack.", source_label: "oracle-backed" }
                ],
                dragging: [
                  { name: "Cold-chain resilience", delta: "manual / deferred", contribution: -8, note: "Cold-chain context remains visible but is not part of the Oracle finance ring computation.", source_label: "manual / deferred" },
                  { name: "Occupancy-style utilisation", delta: "manual / deferred", contribution: -6, note: "Occupancy-style operating signals remain manual / deferred until a separate operational source is shipped.", source_label: "manual / deferred" }
                ]
              }
            },
          {
            key: "cost",
            label: "Operating cost",
              pct: 120,
              value: "120%",
              sub: "operating cost vs plan",
              vsPlan: "Oracle-backed · deterministic",
              story: "Operating cost now renders from the deterministic Oracle cost-vs-plan metric. This card is finance-first and does not imply operational automation beyond the approved Oracle pilot scope.",
            trendLabel: "Weekly operating cost · 13 weeks",
            unit: "SAR M / wk",
              chips: ["Show Oracle cost basis", "Which inputs are manual?", "Compare to plan only"],
              movers: {
                lifting: [{ name: "Oracle operating-cost facts", delta: "deterministic basis", contribution: 14, source_label: "oracle-backed" }],
                dragging: [
                  { name: "Cold-chain fuel burn", delta: "manual / deferred", contribution: -6, note: "Operational logistics context is preserved, but manual / deferred until sourced outside the Oracle finance pilot.", source_label: "manual / deferred" }
                ]
              }
            },
          {
            key: "cash",
            label: "Cash vs floor",
              pct: 120,
              value: "120%",
              sub: "cash vs board floor",
              vsPlan: "Oracle-backed · deterministic",
              story: "The liquidity ring now reflects the deterministic Oracle cash-vs-board-floor result. Manual board-floor input remains explicit and governed.",
            trendLabel: "Cash vs board floor · 13 weeks",
            unit: "SAR B",
              chips: ["Show cash headroom", "Show covenant headroom", "Which inputs are manual?"],
              movers: {
                lifting: [
                  { name: "Oracle CE balances", delta: "cash fact basis", contribution: 34, source_label: "oracle-backed" },
                  { name: "Board-floor input", delta: "approved manual control", contribution: 12, source_label: "manual input" }
                ],
                dragging: [{ name: "Occupancy / footfall overlays", delta: "manual / deferred", contribution: -4, note: "These overlays stay out of the finance ring until an operational source exists.", source_label: "manual / deferred" }]
              }
          }
        ],
        findings: [
          { title: "Oracle-backed finance rings now drive the CEO surface", tag: "Oracle pilot · Finance", detail: "Revenue attainment, EBITDA margin, cash vs board floor, and covenant headroom now render from deterministic Oracle pilot outputs.", tone: "up" },
          { title: "SAR 3.57M is recoverable across 8 deterministic leakage findings", tag: "Oracle pilot · Leakage", detail: "Leakage review stays board-safe because every amount is evidence-backed and reviewer-controlled.", tone: "down" },
          { title: "Operational movers remain visible as manual / deferred", tag: "Oracle pilot · Scope boundary", detail: "Cold-chain, e-Rx, LfL, and occupancy-style items stay in context without implying Oracle-finance automation.", tone: "flat" }
        ],
        developments: [
          { title: "Plan history preserved through the twin-platform buildout", meta: "Product narrative · today", impact: "Completed delivery history remains visible while Oracle pilot conformance becomes the active execution story.", kind: "win" },
          { title: "Manual inputs remain explicit on CEO and CFO surfaces", meta: "Finance controls · today", impact: "Budget, board-floor, covenant, hedge, and contract inputs are visible as controlled supports rather than hidden automation.", kind: "watch" },
          { title: "Operational movers labelled manual / deferred", meta: "Scope truthfulness · today", impact: "Leadership keeps the context, but no one can mistake it for Oracle-finance sourcing.", kind: "watch" }
        ],
        week: [
          { key: "board_prep", day: "Thu", title: "Board meeting", when: "in 3 days", prep: "Two decisions stay open: the FX hedge and the GLP-1 JV. The pack is 80% composed — margin narrative needs your line.", urgent: true, prompt: "Am I on track for the board on Thursday?" },
          { key: "jv", day: "Wed", title: "GLP-1 JV signature", when: "in 2 days", prep: "Supply-lock terms are agreed; cash headroom is confirmed. e-Pharmacy demand model is attached.", urgent: true, prompt: "Can we fund the JV from cash?" },
          { key: "call", day: "Tue", title: "e-Pharmacy GM opportunity call", when: "tomorrow", prep: "Lina wants to pull forward fulfilment capacity. Bring the 12% WoW order curve.", urgent: false, prompt: "Should we pull forward e-Pharmacy fulfilment capacity?" }
        ]
      },
      cfo: {
        health: {
          score: 74,
          headline: "Oracle-first CFO surface is live.",
          body: "The CFO story now starts with Oracle finance ingestion, deterministic KPI outputs, leakage review, and explicit manual-input controls. Generic twin framing is demoted to delivery history.",
          scoreNote: "oracle pilot posture"
        },
        indexLabel: "The financial index",
        assistant: "Atlas",
        assistantRole: "finance chief of staff",
        brief: "This is now an Oracle-first CFO surface: deterministic pilot math first, explicit reconciliation and leakage context second, and no fake automation beyond finance scope.",
        quote: "If a number cannot be traced to Oracle finance or an approved manual input, it does not belong in the CFO pilot surface as automation.",
        by: "Atlas · Group CFO chief of staff",
        secondaryMode: "visible",
        threads: [
          { key: "briefing", title: "EBITDA bridge for the pack", preview: "Walk me through the EBITDA bridge." },
          { key: "hedge", title: "SAR 8.6M recovery sequence", preview: "Where is the SAR 8.6M and how fast can we get it?" },
          { key: "recognition", title: "JV funding", preview: "Can the JV be funded from cash?" }
        ],
        prompts: ["Walk me through the EBITDA bridge.", "Where is the SAR 8.6M?", "Can the JV be funded from cash?"],
        drivers: [
          { key: "revq", label: "Revenue quality", pct: 101, value: "SAR 2.09B", sub: "94% recurring", vsPlan: "+2.3% vs plan", story: "Revenue is ahead and the mix is healthy — 94% recurring, low concentration. NUPCO awards improve quality further next cycle.", trendLabel: "Weekly revenue · 13 weeks", unit: "SAR M / wk", chips: ["Show concentration risk", "Recurring vs one-off", "NUPCO timing"], movers: { lifting: [{ name: "NUPCO contracts", delta: "+SAR 145M annual", contribution: 30 }, { name: "e-Pharmacy recurring", delta: "+12% refill base", contribution: 20 }], dragging: [{ name: "Healthcare one-offs", delta: "lower elective mix", contribution: -10 }] } },
          { key: "bridge", label: "EBITDA bridge", pct: 99, value: "19.2%", sub: "vs 19.4% plan", vsPlan: "−20 bps vs plan", story: "Volume and price add; FX and API cost subtract. The net is a 20 bps miss — a 60% EUR hedge recovers ~15 bps of it.", trendLabel: "Weekly EBITDA margin · 13 weeks", unit: "% margin", chips: ["Model the 60% hedge", "Show the full bridge", "API cost outlook"], movers: { lifting: [{ name: "Volume", delta: "+40 bps", contribution: 24 }, { name: "Price / mix", delta: "+25 bps", contribution: 14 }], dragging: [{ name: "FX", delta: "−35 bps", contribution: -22 }, { name: "API cost", delta: "−30 bps", contribution: -16 }] } },
          { key: "wc", label: "Working capital", pct: 96, value: "58 days", sub: "cash conversion cycle", vsPlan: "+3 days vs plan", story: "DSO 47, DPO 41, DIO 52. The cycle is 3 days long, concentrated in inventory build for the JV.", trendLabel: "Cash conversion cycle · 13 weeks", unit: "CCC days", chips: ["Break down DSO/DPO/DIO", "Inventory unwind plan", "Terms by customer"], movers: { lifting: [{ name: "DPO discipline", delta: "+4 days", contribution: 16 }], dragging: [{ name: "DIO — GLP-1 stock", delta: "+6 days", contribution: -14 }, { name: "DSO — NUPCO terms", delta: "+2 days", contribution: -6 }] } },
          { key: "liq", label: "Liquidity & covenant", pct: 123, value: "SAR 1.48B", sub: "Net debt/EBITDA 1.6x", vsPlan: "2.6x covenant", story: "Cash is 123% of floor; leverage is 1.6x against a 2.6x covenant — a full turn of headroom.", trendLabel: "Cash vs floor · 13 weeks", unit: "SAR B cash", chips: ["Covenant headroom detail", "Fund the JV from cash?", "Refinance window"], movers: { lifting: [{ name: "Collections", delta: "+SAR 145M", contribution: 28 }, { name: "Rate relief", delta: "~SAR 5M/yr", contribution: 10 }], dragging: [{ name: "JV pre-funding", delta: "SAR 60M", contribution: -8 }] } }
        ],
        cashPulse: {
          title: "Cash Pulse",
          note: "four pillars — in, out, at bank, lost. Cash-Leakage is an invokable add-on.",
          pillars: [
            { label: "Cash in", value: "SAR 612M", sub: "collections this month", delta: "+SAR 145M NUPCO", tone: "up" },
            { label: "Cash out", value: "SAR 534M", sub: "disbursed this month", delta: "DPO +4 days", tone: "flat" },
            { label: "At bank", value: "SAR 1.48B", sub: "available liquidity", delta: "+SAR 60M wk", tone: "up" },
            { label: "Lost / leaking", value: "SAR 8.6M", sub: "recoverable group-wide", delta: "invoke leakage scan", tone: "down" }
          ]
        },
        findings: [
          { title: "FX is building a ~SAR 9k margin drag this week", tag: "Group KPI · EBITDA bridge", detail: "Unhedged EUR slice of API purchasing. A 60% hedge neutralises most of it — board decision Thursday.", tone: "flat" },
          { title: "SAR 8.6M is recoverable — leakage scan ready", tag: "Cross-BU finding · Cash-Leakage add-on", detail: "Tamween audit, duplicate-vendor spend, aged AR. One tap opens the drafted recovery sequence.", tone: "down" },
          { title: "Covenant headroom at a full turn (1.6x vs 2.6x)", tag: "Group KPI · Liquidity", detail: "Leverage stays well inside covenant; rate easing adds ~SAR 5M/yr.", tone: "up" }
        ],
        developments: [
          { title: "NUPCO Q1 awards confirmed: +SAR 145M annual", meta: "Capital · 5h ago", impact: "Improves cash timing and revenue quality.", kind: "win" },
          { title: "Tamween audit: SAR 1.2M recoverable", meta: "Tamween Distribution · yesterday", impact: "Folds into the SAR 8.6M recovery.", kind: "watch" },
          { title: "Rates eased — ~SAR 5M/yr interest relief", meta: "Treasury · today", impact: "Supports the JV funding case from cash.", kind: "win" }
        ],
        week: [
          { key: "board_meeting", day: "Thu", title: "Board meeting", when: "in 3 days", prep: "Own the margin and hedge narrative. The EBITDA bridge and covenant slide are composed; confirm the hedge ratio.", urgent: true, prompt: "Walk me through the EBITDA bridge." },
          { key: "jv_funding", day: "Wed", title: "GLP-1 JV funding sign-off", when: "in 2 days", prep: "Fund from cash vs facility — the cash case is cheaper post rate relief.", urgent: true, prompt: "Can the JV be funded from cash?" },
          { key: "treasury", day: "Tue", title: "Treasury hedge execution", when: "tomorrow", prep: "Pre-clear the 60% EUR hedge so it can execute the moment the board approves.", urgent: false, prompt: "Model the 60% hedge." }
        ]
      },
      gm: {
        health: {
          score: 84,
          headline: "Strong week — capacity is the constraint.",
          body: "Orders are +12% week-on-week on the GLP-1 refill cohort and margin is holding. Fulfilment capacity, not demand, is now the limit — the JV signature unlocks supply.",
          scoreNote: "plan health"
        },
        indexLabel: "My unit index",
        assistant: "Iris",
        assistantRole: "ground operator",
        brief: "The growth line is strong; the operating question is whether capacity can keep up without sacrificing service quality.",
        quote: "Demand is healthy — capacity and service discipline decide whether the week stays beautiful or breaks.",
        by: "Iris · BU GM chief of staff",
        secondaryMode: "visible",
        threads: [
          { key: "briefing", title: "Eastern hub bottleneck", preview: "How long until the Eastern hub caps us?" },
          { key: "hedge", title: "Capacity bind", preview: "Where is capacity binding first?" },
          { key: "recognition", title: "Opportunity call", preview: "What do I owe the CEO before tomorrow’s call?" }
        ],
        prompts: ["How long until the Eastern hub caps us?", "Where is capacity binding first?", "What do I owe the CEO before tomorrow’s call?"],
        drivers: [
          { key: "urev", label: "Unit revenue", pct: 112, value: "SAR 214M", sub: "quarter to date", vsPlan: "+12% vs plan", story: "112% of plan — the refill cohort is compounding. Riyadh and the app channel lead; cold-chain regions lag on capacity.", trendLabel: "Weekly revenue · 13 weeks", unit: "SAR M / wk", chips: ["Where is capacity binding?", "Channel breakdown", "Refill cohort curve"], movers: { lifting: [{ name: "Riyadh region", delta: "+18% orders", contribution: 30 }, { name: "App channel", delta: "+22% conversion", contribution: 22 }], dragging: [{ name: "Eastern region", delta: "capacity-capped", contribution: -10 }] } },
          { key: "ucm", label: "Contribution margin", pct: 103, value: "24.1%", sub: "vs 23.4% plan", vsPlan: "+70 bps vs plan", story: "Margin is ahead on basket mix and lower last-mile cost. GLP-1 pull-through carries a healthy attach rate.", trendLabel: "Weekly contribution margin · 13 weeks", unit: "% margin", chips: ["Attach-rate detail", "Last-mile cost drivers", "Promo ROI"], movers: { lifting: [{ name: "Basket mix", delta: "+50 bps", contribution: 18 }, { name: "Last-mile cost", delta: "−2%", contribution: 10 }], dragging: [{ name: "Promo intensity", delta: "+1 pt", contribution: -6 }] } },
          { key: "ucost", label: "Cost to serve", pct: 98, value: "SAR 38 / order", sub: "vs SAR 39 plan", vsPlan: "−2% vs plan", story: "Below plan on route density and warehouse automation. Eastern region is the outlier as volume outruns capacity.", trendLabel: "Cost to serve · 13 weeks", unit: "SAR / order", chips: ["Capacity plan", "Automation payback", "Surge cost detail"], movers: { lifting: [{ name: "Route density", delta: "−5%", contribution: 16 }], dragging: [{ name: "Eastern surge cost", delta: "+8%", contribution: -10 }] } },
          { key: "usla", label: "Fulfilment SLA", pct: 100, value: "2.0 days", sub: "96.5% on-time", vsPlan: "on plan", story: "Holding the 2-day promise despite the order surge. Slippage risk is the Eastern region without added capacity.", trendLabel: "Fulfilment lead time · 13 weeks", unit: "days", chips: ["On-time by region", "Capacity vs SLA", "Peak readiness"], movers: { lifting: [{ name: "Riyadh hub", delta: "1.7 days", contribution: 14 }], dragging: [{ name: "Eastern region", delta: "2.6 days", contribution: -12 }] } }
        ],
        owedUpward: {
          title: "What I owe upward",
          note: "commentary that rolls up to the Group CEO with the number.",
          items: [
            { to: "to Group CEO", on: "Revenue mover · e-Pharmacy +12%", status: "authored", note: "Orders +12% WoW on the GLP-1 refill cohort; fulfilment holding at 2-day SLA. Pushing the JV signature to lock supply." },
            { to: "to Group CFO", on: "Working capital · refill inventory", status: "draft", note: "Pre-stocking GLP-1 to protect the SLA — DIO up ~6 days, unwinds after JV supply lands." },
            { to: "to Board pack", on: "e-Pharmacy opportunity call", status: "due-tomorrow", note: "Not yet authored — your line goes here." }
          ]
        },
        findings: [
          { title: "Refill cohort is compounding — +12% WoW", tag: "Unit KPI · Revenue", detail: "The GLP-1 refill base is now the growth engine. Retention is 91%; capacity is the only ceiling.", tone: "up" },
          { title: "Eastern region capacity will bind within 2 weeks", tag: "Sub-unit · Fulfilment", detail: "Order growth outruns the Eastern hub. Shift volume or pull forward the automation line.", tone: "flat" },
          { title: "Last-mile cost down 5% on route density", tag: "Unit KPI · Cost to serve", detail: "Density gains are funding the margin beat.", tone: "up" }
        ],
        developments: [
          { title: "App conversion hit 22% — new high", meta: "Digital · 3h ago", impact: "Supports the revenue beat; protect the funnel through peak.", kind: "win" },
          { title: "Eastern hub at 94% utilisation", meta: "Operations · today", impact: "SLA risk in ~2 weeks without added capacity.", kind: "watch" }
        ],
        week: [
          { key: "ceo_call", day: "Tue", title: "Opportunity call with the CEO", when: "tomorrow", prep: "Ask to pull forward fulfilment capacity. Bring the 12% WoW curve and the Eastern bottleneck.", urgent: true, prompt: "Should we pull forward e-Pharmacy fulfilment capacity?" },
          { key: "jv_model", day: "Wed", title: "JV demand model review", when: "in 2 days", prep: "Confirm the refill demand curve feeding the JV supply lock.", urgent: true, prompt: "What do I owe the CEO before tomorrow’s call?" },
          { key: "automation", day: "Fri", title: "Automation line decision", when: "in 4 days", prep: "Payback case for the Eastern automation line.", urgent: false, prompt: "How long until the Eastern hub caps us?" }
        ]
      },
      bucfo: {
        health: {
          score: 66,
          headline: "Margin recovering — leakage and cutover in flight.",
          body: "Revenue is flat to plan and margin is below, dragged by a SAR 1.2M leakage and the S/4HANA cutover. Recovery is sequenced; the variance note is owed upward today.",
          scoreNote: "plan health"
        },
        indexLabel: "My unit financials",
        assistant: "Argus",
        assistantRole: "exacting controller",
        brief: "Tamween’s story is about exact control: leakage, DSO, and cutover recovery — not decorative reassurance.",
        quote: "The number improves only when the recovery sequence is real and the commentary rides up with it.",
        by: "Argus · BU CFO chief of staff",
        secondaryMode: "visible",
        threads: [
          { key: "briefing", title: "Variance note to Group CFO", preview: "Draft my variance note on the margin drag." },
          { key: "hedge", title: "Recovery sequence", preview: "What is the SAR 1.2M recovery path?" },
          { key: "recognition", title: "Cutover risk", preview: "What still needs closing before the cost line steps down?" }
        ],
        prompts: ["Draft my variance note on the margin drag.", "What is the SAR 1.2M recovery path?", "What still needs closing before the cost line steps down?"],
        drivers: [
          { key: "drev", label: "Revenue", pct: 100, value: "SAR 421M", sub: "quarter to date", vsPlan: "flat vs plan", story: "On plan — institutional volume is steady, retail wholesale is soft. NUPCO renewal protects the base into next quarter.", trendLabel: "Weekly revenue · 13 weeks", unit: "SAR M / wk", chips: ["Revenue by customer", "NUPCO renewal terms", "Wholesale softness"], movers: { lifting: [{ name: "NUPCO institutional", delta: "+3%", contribution: 14 }], dragging: [{ name: "Retail wholesale", delta: "−4%", contribution: -12 }] } },
          { key: "dmargin", label: "Contribution margin", pct: 94, value: "8.9%", sub: "vs 9.5% plan", vsPlan: "−60 bps vs plan", story: "94% of plan — the SAR 1.2M leakage and cutover dual-running cost are the drag. Recovery sequence targets 9.5% by year-end.", trendLabel: "Weekly contribution margin · 13 weeks", unit: "% margin", chips: ["Leakage recovery plan", "Cutover cost timeline", "Vendor concentration"], movers: { lifting: [{ name: "Freight renegotiation", delta: "+20 bps", contribution: 12 }], dragging: [{ name: "Leakage (audit)", delta: "SAR 1.2M", contribution: -22 }, { name: "Cutover dual-run", delta: "−30 bps", contribution: -14 }] } },
          { key: "dwc", label: "Receivables", pct: 92, value: "DSO 54 days", sub: "vs 49 plan", vsPlan: "+5 days vs plan", story: "DSO is running 5 days long on two slow institutional accounts. Collections plan is in place; SAR 1.2M of the leakage is recoverable AR.", trendLabel: "Days sales outstanding · 13 weeks", unit: "DSO days", chips: ["Aged AR detail", "Collections sequence", "Customer terms"], movers: { lifting: [{ name: "Retail collections", delta: "−2 days", contribution: 10 }], dragging: [{ name: "Institutional A", delta: "+6 days", contribution: -16 }, { name: "Institutional B", delta: "+3 days", contribution: -8 }] } },
          { key: "dcost", label: "Operating cost", pct: 102, value: "SAR 47M", sub: "quarter to date", vsPlan: "+2% vs plan", story: "Slightly hot on cutover dual-running. Cost falls below plan once the S/4HANA cutover completes and legacy is retired.", trendLabel: "Weekly operating cost · 13 weeks", unit: "SAR M / wk", chips: ["Cutover savings curve", "Legacy retirement date", "Cost by function"], movers: { lifting: [{ name: "Route optimisation", delta: "−1.5%", contribution: 10 }], dragging: [{ name: "Cutover dual-run", delta: "+SAR 0.9M", contribution: -16 }] } }
        ],
        owedUpward: {
          title: "Variance commentary I owe",
          note: "authored notes that roll up with each number.",
          items: [
            { to: "to Group CEO", on: "EBITDA mover · Distribution dragging", status: "authored", note: "Recovering the SAR 1.2M leakage and cutting cost via the S/4HANA cutover; targeting 9.5% margin by year-end." },
            { to: "to Group CFO", on: "Recovery · SAR 8.6M group scan", status: "due-today", note: "Confirm SAR 1.2M of Tamween AR as recoverable and attach the collections sequence." },
            { to: "to Audit committee", on: "Leakage controls", status: "draft", note: "Awaiting the final control memo." }
          ]
        },
        findings: [
          { title: "SAR 1.2M leakage confirmed by audit", tag: "Unit KPI · Margin", detail: "Concentrated in two institutional accounts and a duplicate-vendor line. Recovery sequence is drafted.", tone: "down" },
          { title: "Cutover dual-running is +30 bps of cost", tag: "Unit KPI · Operating cost", detail: "Temporary while S/4HANA and legacy run in parallel.", tone: "flat" },
          { title: "Freight renegotiation locked +20 bps", tag: "Sub-line · Logistics", detail: "New carrier terms partially offset the leakage drag from next month.", tone: "up" }
        ],
        developments: [
          { title: "Institutional A aged AR crossed 90 days", meta: "Credit · today", impact: "Lifts DSO; collections call is scheduled.", kind: "watch" },
          { title: "S/4HANA cutover passed UAT", meta: "Transformation · yesterday", impact: "Legacy retirement is on track; cost relief comes next quarter.", kind: "win" }
        ],
        week: [
          { key: "variance_note", day: "Mon", title: "Variance note to Group CFO", when: "due today", prep: "Confirm SAR 1.2M recoverable and attach the collections sequence.", urgent: true, prompt: "Draft my variance note on the margin drag." },
          { key: "collections", day: "Tue", title: "Institutional A collections call", when: "tomorrow", prep: "Aged AR is beyond 90 days. Bring the payment-plan options.", urgent: true, prompt: "What is the SAR 1.2M recovery path?" },
          { key: "cutover", day: "Thu", title: "Cutover go-live review", when: "in 3 days", prep: "Confirm the legacy retirement date and the cost step-down.", urgent: false, prompt: "What still needs closing before the cost line steps down?" }
        ]
      },
      logistics: {
        health: {
          score: 80,
          headline: "Resilience is carrying confidence.",
          body: "Cold-chain reliability is the quiet strength in the packet. Keep service, continuity, and cost discipline aligned while the board asks for confidence.",
          scoreNote: "resilience"
        },
        indexLabel: "The resilience index",
        assistant: "Vega",
        assistantRole: "logistics chief of staff",
        brief: "Cold-chain and service reliability remain the calm strength in the packet; continuity needs to stay elegant and boring.",
        quote: "Cold-chain credibility lets the board focus on strategy instead of firefighting, provided cost stays disciplined.",
        by: "Vega · logistics chief of staff",
        secondaryMode: "visible",
        threads: [
          { key: "briefing", title: "Cold-chain watch", preview: "What keeps service credibility strongest this week?" },
          { key: "hedge", title: "Continuity risk", preview: "Where could continuity slip before the board?" },
          { key: "recognition", title: "Operational win", preview: "Which logistics win should the board hear?" }
        ],
        prompts: ["What keeps service credibility strongest this week?", "Where could continuity slip before the board?", "Which logistics win should the board hear?"],
        drivers: [
          { key: "service", label: "Service", pct: 101, value: "96.5% on-time", sub: "continuity and delivery", vsPlan: "+1 pt vs plan", story: "Service resilience should feel calm and precise, not noisy — this is a confidence signal.", trendLabel: "Weekly service continuity", unit: "%", chips: ["continuity", "board confidence", "service proof"], movers: { lifting: [{ name: "Riyadh hub", delta: "1.7 days", contribution: 14 }, { name: "Cold-chain ops", delta: "record reliability", contribution: 20 }], dragging: [{ name: "Eastern surge", delta: "capacity pressure", contribution: -10 }] } },
          { key: "cold_chain", label: "Cold-chain", pct: 99, value: "99.4%", sub: "integrity", vsPlan: "record week", story: "Cold-chain reliability belongs in the packet as proof of operational discipline, not dashboard theatre.", trendLabel: "Cold-chain integrity", unit: "%", chips: ["record week", "quality preserved", "supply watch"], movers: { lifting: [{ name: "Summer peak control", delta: "no excursions", contribution: 24 }], dragging: [{ name: "Eastern alert", delta: "transient, cleared", contribution: -4 }] } },
          { key: "cost", label: "Logistics cost", pct: 98, value: "SAR 38/order", sub: "cost to serve", vsPlan: "within tolerance", story: "Fuel and surge cost stay in view, but cost discipline has not broken the resilience story.", trendLabel: "Cost to serve", unit: "SAR / order", chips: ["fuel watch", "route density", "surge plan"], movers: { lifting: [{ name: "Route density", delta: "−5%", contribution: 12 }], dragging: [{ name: "Fuel", delta: "+2.6% vs plan", contribution: -9 }] } },
          { key: "readiness", label: "Board readiness", pct: 101, value: "room confidence", sub: "operations story clear", vsPlan: "board-safe", story: "Operations should arrive in the room as proof and reassurance, not as a scramble.", trendLabel: "Readiness posture", unit: "signal", chips: ["board-safe", "approved narrative", "service proof"], movers: { lifting: [{ name: "Record cold-chain week", delta: "confidence up", contribution: 18 }], dragging: [{ name: "Capacity bind", delta: "watch closely", contribution: -8 }] } }
        ],
        findings: [
          { title: "Cold-chain hit 99.4% — best ever", tag: "Resilience", detail: "No excursions in the last 30 days through the summer peak.", tone: "up" },
          { title: "Eastern region surge remains the one service risk", tag: "Capacity", detail: "Extra load needs careful orchestration before it shows in the board packet.", tone: "flat" },
          { title: "Route density keeps last-mile cost in line", tag: "Cost to serve", detail: "Density gains are offsetting surge pressure.", tone: "up" }
        ],
        developments: [
          { title: "Recognition drafted for the Logistics GM", meta: "Hermes + Vega · today", impact: "Ready to ride upward into the weekly note.", kind: "win" },
          { title: "Eastern transient alert cleared", meta: "Cold-chain monitor · yesterday", impact: "No ongoing temperature risk remains in the packet.", kind: "watch" }
        ],
        week: [
          { key: "continuity", day: "Tue", title: "Continuity review", when: "tomorrow", prep: "Re-check the Eastern hub and route-density assumptions before the room.", urgent: true, prompt: "Where could continuity slip before the board?" },
          { key: "recognition", day: "Thu", title: "Recognition note", when: "in 3 days", prep: "Carry the cold-chain record into the board narrative without overplaying it.", urgent: false, prompt: "Which logistics win should the board hear?" }
        ]
      }
    },
    board: {
      assistant: "Minerva",
      meeting: { title: "Q2 Board Meeting", when: "in 3 days", date: "Thu 18 Jun · 14:00", room: "Riyadh HQ + remote" },
      governance: "Nothing reaches the board until the Group CEO approves it. Between meetings, board assistants run on the last frozen snapshot — no live org data.",
      kpis: [
        { key: "revenue", label: "Revenue", pct: 102, value: "SAR 2.09B", sub: "quarter to date" },
        { key: "ebitda", label: "EBITDA margin", pct: 99, value: "19.2%", sub: "vs 19.4% plan" },
        { key: "cash", label: "Cash vs floor", pct: 123, value: "SAR 1.48B", sub: "vs SAR 1.2B floor" },
        { key: "localisation", label: "Vision 2030 localisation", pct: 104, value: "38.4% Saudization", sub: "vs 37% target" }
      ],
      decks: [
        { title: "Group performance & plan health", by: "Office of the CEO", status: "approved", pages: 14, tag: "group KPI" },
        { title: "Margin & the FX hedge decision", by: "Group CFO · Atlas", status: "approved", pages: 9, tag: "decision" },
        { title: "GLP-1 JV — supply lock & funding", by: "e-Pharmacy + Capital", status: "approved", pages: 11, tag: "decision" },
        { title: "Tamween recovery & cutover", by: "BU CFO · Argus", status: "pending CEO approval", pages: 7, tag: "rolled-up" }
      ],
      supplementary: [
        { q: "What is the downside if EUR strengthens after a 60% hedge?", to: "Group CEO", status: "sent" },
        { q: "Can the JV be funded fully from cash without touching the facility?", to: "Group CFO", status: "answered" }
      ],
      livePrompts: [
        "Why is EBITDA 20 bps under plan?",
        "Show the hedge downside",
        "Is the JV funded from cash?"
      ],
      actions: [
        { item: "Ratify the 60% EUR hedge", owner: "Group CFO", due: "on approval" },
        { item: "Approve GLP-1 JV signature", owner: "Group CEO", due: "this week" },
        { item: "Review Tamween recovery at Q3", owner: "Audit committee", due: "Q3" }
      ],
      summary: "Board endorsed the margin-protection plan and ratified the hedge; approved the GLP-1 JV subject to final supply terms. Recovery of SAR 8.6M will be reviewed at Q3. Full minutes are uploaded by the board secretary."
    },
    activity: {
      line: "5 agents · 25 steps · 15 tool calls — recovered SAR 8.6M of leakage and composed 80% of the board pack",
      metrics: [{ k: "agents", v: "5" }, { k: "steps", v: "25" }, { k: "tool calls", v: "15" }, { k: "value found", v: "SAR 8.6M" }],
      log: [
        { t: "06:14", who: "Hermes", a: "Engaged Board-pack composer to assemble the margin narrative." },
        { t: "06:11", who: "Board-pack composer", a: "Delegated the EBITDA bridge to the Spreadsheet sub-agent." },
        { t: "06:05", who: "Leakage scan", a: "Recovered SAR 1.2M at Tamween and rolled it into SAR 8.6M group recovery." },
        { t: "06:01", who: "Hermes", a: "Dispatched Argus to confirm collectability; awaiting reply." },
        { t: "05:55", who: "Cold-chain monitor", a: "Logged 99.4% record and drafted recognition for the Logistics GM." }
      ]
    },
    runningAgents: [
      { id: "boardpack", name: "Board pack composer", by: "Office of the CEO", status: "running", progress: 80, tag: "board prep", doing: "Drafting the margin narrative — 9 of 11 sections assembled.", log: [{ t: "06:14", a: "Pulled the EBITDA bridge and covenant slide from the financial index." }, { t: "06:11", a: "Assembled revenue, cash, and resilience sections from 8 BU ledgers." }, { t: "06:08", a: "Opened composition against board-approved plan v4." }] },
      { id: "leakage", name: "Leakage recovery scan", by: "Group CFO", status: "running", progress: 38, tag: "cash · governance", doing: "Scanning for recoverable spend — 3 of 8 BUs, SAR 8.6M identified so far.", log: [{ t: "06:02", a: "Confirmed SAR 1.2M recoverable at Tamween." }, { t: "05:58", a: "Flagged duplicate-vendor spend across Distribution and Logistics." }, { t: "05:55", a: "Invoked Cash-Leakage add-on on the group ledger." }] },
      { id: "hedge", name: "FX hedge pre-clearance", by: "Treasury", status: "approval", progress: 100, tag: "EBITDA · acts on approval", doing: "A 60% EUR hedge is staged to execute the moment the board approves. Needs your sign-off to act.", log: [{ t: "06:05", a: "Staged 60% EUR hedge order — held, not sent." }, { t: "06:04", a: "Modelled hedge in thinking mode: recovers ~15 bps of margin." }, { t: "06:01", a: "Detected ~SAR 9k/wk FX drag on unhedged API purchasing." }] },
      { id: "variance", name: "Variance commentary collector", by: "Group CFO", status: "running", progress: 75, tag: "rolled-up", doing: "Gathering BU commentary to ride up with each mover — 6 of 8 GMs have responded.", log: [{ t: "06:10", a: "Attached Faisal Noor’s note to the Distribution EBITDA drag." }, { t: "06:07", a: "Attached Lina Haddad’s note to the e-Pharmacy revenue lift." }, { t: "05:50", a: "Requested variance notes from 8 BU leaders." }] },
      { id: "coldchain", name: "Cold-chain integrity monitor", by: "Pharma Logistics", status: "standing", progress: 100, tag: "resilience · continuous", doing: "Watching continuously — 99.4% integrity, no excursions in 30 days.", log: [{ t: "06:00", a: "Logged a new record: 99.4% integrity through the summer peak." }, { t: "yest", a: "Cleared a transient temperature alert at the Eastern hub." }, { t: "yest", a: "Recognition drafted for the Logistics GM → Developments." }] },
      { id: "jvmodel", name: "GLP-1 JV demand model", by: "e-Pharmacy", status: "queued", progress: 0, tag: "think-mode", doing: "Queued — waiting on the refreshed e-Pharmacy order curve before re-running the supply-lock model.", log: [{ t: "05:45", a: "Queued behind the order-curve refresh due tomorrow." }] }
    ],
    discoverAgents: [
      { id: "covenant", glyph: "⚖", name: "Covenant sentinel", source: "native", by: "StrategyOS", desc: "Watches leverage against every covenant and warns before you near a limit.", connector: "Treasury · loan agreements" },
      { id: "workingcap", glyph: "◴", name: "Working-capital optimiser", source: "native", by: "StrategyOS", desc: "Models DSO / DPO / DIO moves and proposes the cash-release sequence.", connector: "S/4HANA · AR / AP" },
      { id: "scenario", glyph: "◇", name: "Scenario planner", source: "native", by: "StrategyOS", desc: "Runs multi-driver what-ifs across the group — think-mode, no side effects.", connector: "knowledge graph" },
      { id: "tender", glyph: "◎", name: "Tender radar", source: "market", by: "GovDesk", desc: "Scans NUPCO and MoH tenders and matches them to your portfolio and capacity.", connector: "gov procurement feeds" },
      { id: "supplier", glyph: "⬡", name: "Supplier-risk monitor", source: "market", by: "ChainLens", desc: "Tracks API supplier disruption, lead times, and geopolitical exposure.", connector: "supplier EDI" },
      { id: "esg", glyph: "◷", name: "Vision 2030 & ESG reporter", source: "market", by: "Tatweer", desc: "Tracks Saudization, localisation, and ESG metrics against your targets.", connector: "HR · ESG systems" }
    ],
    subtools: [
      { name: "Spreadsheet", glyph: "▦", desc: "Builds and audits models — the EBITDA bridge and hedge scenarios." },
      { name: "Document & PDF", glyph: "▤", desc: "Reads decks and contracts; drafts the board pack." },
      { name: "Calls at scale", glyph: "☏", desc: "Runs structured outreach — collections and supplier check-ins." },
      { name: "Marketing content", glyph: "✎", desc: "Drafts announcements and recognition notes on-brand." }
    ],
    networkMeta: {
      label: "Assistant Network",
      hint: "How current and deeply-used each leader’s assistant is — your read on data quality and AI adoption across Mizan.",
      target: 80
    },
    network: [
      { persona: "ceo", assistant: "Hermes", who: "Khalid Al-Rashed", unit: "Group · CEO", score: 92, freshness: "live · 6 min ago", usage: "daily", depth: "deep", tone: "up" },
      { persona: "cfo", assistant: "Atlas", who: "Sara Al-Mahmoud", unit: "Group · CFO", score: 89, freshness: "live · 12 min ago", usage: "daily", depth: "deep", tone: "up" },
      { persona: "gm", assistant: "Iris", who: "Lina Haddad", unit: "e-Pharmacy · GM", score: 84, freshness: "today · 2h ago", usage: "daily", depth: "good", tone: "up" },
      { persona: "logistics", assistant: "Vega", who: "Hassan Tarek", unit: "Pharma Logistics · GM", score: 96, freshness: "live · 4 min ago", usage: "hourly", depth: "deep", tone: "up" },
      { persona: "bucfo", assistant: "Argus", who: "Yusuf Rahman", unit: "Tamween · BU CFO", score: 78, freshness: "today · 5h ago", usage: "weekly", depth: "good", tone: "flat" },
      { persona: "mfg", assistant: "Orion", who: "Dana Saleh", unit: "Manufacturing · GM", score: 71, freshness: "yesterday", usage: "weekly", depth: "partial", tone: "flat" },
      { persona: "hc", assistant: "Juno", who: "Omar Said", unit: "Healthcare Svcs · GM", score: 61, freshness: "4 days ago", usage: "rare", depth: "thin", tone: "down" },
      { persona: "cap", assistant: "Nova", who: "Rami Khoury", unit: "Capital · GM", score: 88, freshness: "today · 3h ago", usage: "daily", depth: "good", tone: "up" }
    ],
    a2a: [
      { id: "x1", with: "Iris", unit: "e-Pharmacy", status: "active", topic: "fulfilment capacity", messages: [
        { from: "Hermes", text: "Khalid meets Lina tomorrow. Confirm the Eastern hub timeline and the automation payback." },
        { from: "Iris", text: "Crosses 100% utilisation in ~12 days. Automation line payback is 7 months; I’ll attach the curve." },
        { from: "Hermes", text: "Good. I’ll set it as a decision item for the call and flag cash headroom to Atlas." }
      ] },
      { id: "x2", with: "Argus", unit: "Tamween", status: "awaiting", topic: "SAR 1.2M recovery", messages: [
        { from: "Hermes", text: "The board pack needs the leakage recovery confirmed. Is the SAR 1.2M collectable this quarter?" },
        { from: "Argus", text: "Confirming with two institutional accounts — answer by end of day. Collections sequence drafted." }
      ] }
    ],
    graph: {
      questions: [
        { id: "q_fx", label: "Why is margin missing plan?", focus: ["fx", "api", "ebitda", "mfg", "dist"] },
        { id: "q_leak", label: "Where is the SAR 8.6M?", focus: ["leak", "tamween", "vendorx", "ar_a", "ar_b"] },
        { id: "q_jv", label: "Can we fund the GLP-1 JV?", focus: ["cash", "jv", "epharm", "nupco"] }
      ],
      nodes: [
        { id: "plan", label: "Board plan v4", x: 50, y: 50, r: 13 },
        { id: "ebitda", label: "EBITDA margin", x: 50, y: 24, r: 11 },
        { id: "cash", label: "Cash vs floor", x: 74, y: 32, r: 11 },
        { id: "fx", label: "FX exposure", x: 30, y: 12, r: 8 },
        { id: "api", label: "API input cost", x: 44, y: 8, r: 8 },
        { id: "mfg", label: "Manufacturing", x: 22, y: 30, r: 9 },
        { id: "dist", label: "Tamween Distribution", x: 30, y: 46, r: 9 },
        { id: "epharm", label: "e-Pharmacy", x: 70, y: 60, r: 9 },
        { id: "leak", label: "Leakage finding", x: 18, y: 60, r: 8 },
        { id: "tamween", label: "Tamween audit", x: 12, y: 46, r: 7 },
        { id: "vendorx", label: "Vendor X", x: 10, y: 72, r: 7 },
        { id: "ar_a", label: "Institutional A · AR", x: 26, y: 76, r: 7 },
        { id: "ar_b", label: "Institutional B · AR", x: 40, y: 80, r: 7 },
        { id: "nupco", label: "NUPCO contract", x: 86, y: 48, r: 8 },
        { id: "jv", label: "GLP-1 JV", x: 84, y: 70, r: 8 },
        { id: "cust", label: "Pharmacy Retail", x: 60, y: 78, r: 8 }
      ],
      edges: [
        ["plan", "ebitda"], ["plan", "cash"], ["ebitda", "fx"], ["ebitda", "api"], ["ebitda", "mfg"],
        ["ebitda", "dist"], ["fx", "api"], ["dist", "leak"], ["leak", "tamween"], ["leak", "vendorx"],
        ["leak", "ar_a"], ["leak", "ar_b"], ["dist", "tamween"], ["cash", "nupco"], ["cash", "jv"],
        ["jv", "epharm"], ["nupco", "dist"], ["epharm", "cust"], ["plan", "epharm"], ["cash", "epharm"]
      ]
    ]
  };
})();
