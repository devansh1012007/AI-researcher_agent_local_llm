Requirements : 

- Making a smart , local and useful research agent who has expertise to do normal research and specialized research for Start ups and financial topics  
- I want it to give me better results. Google's deep research with pro mode. This will be archived by a better memory agent and carefully reading 100s of valid websites and noting down all the relevant information in a Markdown file. After recursively reading all the web scraped data and saving all the important clues and information in [info.MD](http://info.MD) file . Agent will understand all the data and try to find all the missing informations, then it tells what are the thing to search next (top 5 queries/searches) such that it finds all the missing information and try to get more depth, and then it compresses [info.MD](http://info.MD) just enough to remove all the duplications and highlight all the blind spots. This happens recursively for 5-10 times (depends on severity). The user will be returned with the full [info.MD](http://info.MD) with links for all the data sources in it. And final output which explains the full research in detail.  
- After the research is done , user has the option do do more research or cover the data from [info.md](http://info.md) into a vector file and llm can run a vector search query and answer to user’s questions regarding the research   
- This agent should also help user to Formulate a Hypothesis and Design the methodology but for this the user needs to change mode from data gather to respective mode . where the agent will run in a recursive agentic loop to get more data , query vector db and then generate **all the possible hypotheses** . similarly the Methodology designer will design all possible Methodology for ‘n’ number of hypotheses that user secrets or sends from their understanding.  
- The Startup mode will do the same where it will do the market research and find out all the possible data about market is similar recursive behavior as data collector, and then it will generate all the possible market niche / requirements just like making hypothesis. Then it will help user to make ideas to capture the market niche and generate possible tests to validate the need in the market.   
- Mediatory 4 step process for the agent (broken down into pieces and modes) : Define the Problem/requirement clearly → Conduct a Literature Review / data collection form internet → Formulate a Hypothesis/market need → Design the Methodology / possible ideas and testing stratify   
- User should be able to provide files if available , for better research and data gathering  
- There should be a recursive agentic loop in each step and mode . All the data AI gathers should be saved in markdown file  
- Contents of [info.MD](http://info.MD) → all the relevant data rathered with sources   
- Contents of Problem[.MD](http://info.MD) → A detailed description of the problem we are solving and the multiple sub problems we are solving  
- Contents of hypotysis[.MD](http://info.MD) or maket\_niches.MD → detailed content regarding all the possible market niches and hypothysis  
- Contents of Methodology[.MD](http://info.MD) or [Ideas.MD](http://Ideas.MD) → detailed content regarding all the possible Methodologies and Ideas  
- Contents of principles[.MD](http://info.MD) → all the working principles of AI and the detailed description of how it should work.  
- Tools : search online using agent swarms , query vector\_data, ask user for preference , decisions and requirements from outcome in the given situation, edit files, create files, look at content in file and list all the files in the directory.  
- Problem/requirement clarity agentic : initial prompt → checks if problems and requirements are clear , if not then this step will run until the agent is satisfied , if yes then if generates  clean requirements and problem with all the detail and specifications  → take the clean detailed problem as input and breaks it down into sub problems and write [problem.MD](http://problem.MD) containing the problem in detail, all the surrounding problems and what needs to be solved → \[end\] human reviews the [problem.MD](http://problem.MD) , makes edits if needed and then accepts it for next step.   
- Data gatherer agentic loop : [Problem.MD](http://Problem.MD) as input → generates all the possible search queries and then adds them to [info.MD](http://info.MD) → selects queries from the stacks (or all if needed) and then converts them to consecutive/follow up questions passes them to next stage or to the tool call → this is tool call or next stage that searches all the specified queries/searches and then scraped data from top 7 website then a small LLM is fed the web scrap of 1 website search and add relevant data, conncetions and figures   
   to [info.MD](http://info.MD) (it only has write assess) . this happens recursively to scrape of all the website. → compactor step, here the agent agressively updates the [info.md](http://info.md) file and adds more relevant connections and conclusions.  → repeat this full cycle 5-10 times → conclusion layer   
- Hypothesis agent loop : reads user query and vector searches the replacement data → write down all the possible hypothesis in [hypothesis.md](http://hypothesis.md) file → this layer recursively gathers data and adds content to all possible hypothesis one by one → repeat until there is no more content/details to add → critique agent cretices all the hypothesis → LLM refines each of the hypothesis recursively (repeated step until llm is satisfied) → critique and improvement cycle is ran couple of times and then final output is given to user.   
- Finance research magnetic cycle : gathers data from internet and sources and urls provided by users. After recursively searching about stock and understanding all the different valuation matrices and adds content to info.md . It output clean data in info.md and conclusions → the conclusion and data in [info.md](http://info.md) is fed in and the model is asked to list all the blind spots and unreasoned matrices (ie if there is no reasoning given behind why a given value is so high or low) . → model research aging according to the critiques response and tries to improve and edit [info.md](http://info.md) → the critique and improvement cycle is repeated till there is no blind spots or unreasoned anomaly left → Then the final conclusion is made . If there are multiple stocks or companies then this process is process for the next company.

Constrains : 

- Local hardware → use smaller model for extracting data from web-scrapes and larger reasoning model for compression by editing, finding Blindspots, next search queries, and final output. 

Plan : 

\# Grounded Recursive Research Agent Planning Document

\*\*Project Name\*\*: Grounded Agentic Researcher (GAR)  
\*\*Version\*\*: 1.0  
\*\*Date\*\*: May 30, 2026

\#\# Step 0: Project Brief

\*\*Problem Statement\*\*:   
Researchers, startup founders, and financial analysts waste excessive time on shallow, hallucination-prone web research. Existing tools (Google, Perplexity, etc.) lack depth, verification, memory, and structured recursive analysis for complex topics like market research or investment due diligence. We are building a local, tool-augmented, multi-step agentic system that performs deep, grounded, verifiable research with persistent Markdown knowledge bases and controlled iteration.

\*\*Target Users\*\*:   
\- Solo startup founders and indie hackers (primary, 1-10 concurrent researches)  
\- Financial analysts and investors  
\- Researchers and consultants  
\- Scale: Individual to small teams (initially single-user local deployment)

\*\*Success Metrics\*\*:  
\- Research completeness: Cover 80%+ of identified blind spots within 5-8 iterations  
\- Hallucination rate: \<5% (verified via human audit on sample topics)  
\- User satisfaction: 90% of users report deeper insights than standard LLM research  
\- Time efficiency: Produce comprehensive report 3-5x faster than manual deep research  
\- Grounding: 95%+ of claims in final output have direct source citations

\*\*Core Features\*\*:  
\*\*Must-have\*\*:  
\- Problem clarification with user feedback  
\- Recursive data gathering with web tools \+ file persistence (\`info.md\`)  
\- Anti-hallucination (extraction, verification, critic loops)  
\- Hypothesis / Niche generation with evidence  
\- Methodology / Ideas designer  
\- Q\&A over research archive

\*\*Should-have\*\*:  
\- Finance & Startup specialized modes  
\- Vector search support  
\- User file ingestion  
\- Research log audit trail

\*\*Could-have\*\*:  
\- Multi-agent orchestration UI  
\- Diagram generation for hypotheses  
\- Export to various formats

\*\*Won't-have (Phase 1)\*\*: Cloud deployment, real-time collaboration, advanced ML training.

\*\*Constraints\*\*:  
\- Time: MVP in 2-4 weeks (part-time)  
\- Budget: Zero (local, open tools)  
\- Team: Solo  
\- Existing: Leverage sandbox tools (\`web\_search\`, \`open\_page\_with\_find\`, file ops)

\#\# Step 1: Requirements Deep Dive

\#\#\# Functional Requirements  
\*\*User Stories\*\*:  
\- As a user, I can input a research topic and get clear problem breakdown (\`problem.md\`)  
\- As a user, I can trigger recursive data collection that iteratively improves \`info.md\`  
\- As a user, I can review/edit intermediate files before proceeding  
\- As a user, I can switch modes (Data, Hypothesis, Methodology, Startup, Finance)  
\- As a user, I can query the research archive for answers with citations

\*\*MoSCoW Prioritization\*\*:  
\- \*\*Must\*\*: Problem clarity, Data gatherer loop, File persistence, Basic hypothesis generation, Grounding mechanisms  
\- \*\*Should\*\*: Critic loops, Finance specialization, Q\&A, start-up specialization,Focused Extractor  
\- \*\*Could\*\*: Advanced vector DB, Multi-user  
\- \*\*Won't\*\*: Real browser automation, Paid APIs

\#\#\# Non-Functional Requirements  
\- \*\*Performance\*\*: Research cycle \< 5-10 min per iteration (tool-dependent); Q\&A \< 5s  
\- \*\*Scalability\*\*: Handle 1000+ page scrapes per research; single user  
\- \*\*Reliability\*\*: Graceful handling of tool failures, rate limits; checkpointing  
\- \*\*Security\*\*: Local-only, no data exfiltration; handle sensitive research topics  
\- \*\*Maintainability\*\*: Modular Python scripts \+ prompt templates; versioned files  
\- \*\*Observability\*\*: Detailed \`research\_log.md\` with timestamps, queries, diffs  
\- \*\*Cost\*\*: Free (local LLM inference \+ free tools where possible)

\#\# Step 2: High-Level Architecture

\*\*Context Diagram\*\* (Text-based):  
\`\`\`  
Users / Human Reviewer  
       |  
       v  
\[Grounded Agentic Researcher Orchestrator\]  
       |   
       \+-- Tools: web\_search, open\_page\_with\_find, read/edit/write\_file, etc.  
       \+-- External: Web (search engines, websites)  
       \+-- Persistent State: \*.md files (problem, info, hypotheses, etc.)  
       \+-- Optional: Local Vector DB  
\`\`\`

\*\*Component Diagram\*\*:  
\- Orchestrator (Main Python script / REPL loop)  
\- Problem Clarifier Agent  
\- Data Gatherer (Planner \+ Extractor \+ Verifier \+ Compactor)  
\- Hypothesis Generator \+ Critic  
\- Methodology Designer  
\- Q\&A Engine  
\- File Manager

\*\*Data Flow\*\*:  
User Query → Problem.md → Queries → Tool Calls → Raw Data → Extraction → info.md → Synthesis/Critique → Refined info.md → Hypotheses.md → etc.

\*\*Deployment\*\*: Local Python environment in sandbox. Docker for reproducibility later.

\*\*Key Decisions\*\*:  
\- \*\*Monolith\*\*: Yes \- simpler for local agentic control and state management.  
\- \*\*Async\*\*: Tool calls can be parallelized where safe (multiple searches).  
\- \*\*Failures\*\*: Tool rate limits, bad scrapes, LLM drift → Retries \+ fallbacks \+ human pause.  
\- \*\*Resilience\*\*: Checkpoint after each major step.

\#\# Step 3: Data Design

\*\*Core Models\*\* (Markdown-based, structured sections):  
\- Research Project: Topic, problem.md, info.md, etc.  
\- Info Entry: Claim, Evidence (quote), Source URL, Timestamp, Confidence, Tags  
\- Hypothesis: Description, Evidence List, Assumptions, Critiques, Refinements

\*\*Database\*\*: Markdown files \+ optional SQLite for indexing / vector chunks.  
\*\*Justification\*\*: Simple, human-readable, git-friendly, no server needed.

\*\*Patterns\*\*: Write-heavy during gathering, read-heavy during synthesis/Q\&A.  
\*\*Caching\*\*: Tool result caching (simple JSON cache).  
\*\*Consistency\*\*: Append-only with versioning via timestamps

\#\# Step 4: Tech Stack & Library Decisions

\*\*Orchestrator Language\*\*: Python 3.11+  
\- \*\*Reason\*\*: Excellent tool integration, file handling, LLM prompting.  
\- \*\*Risks\*\*: None major.

\*\*LLM Interface\*\*: local models via llama.cpp or similar (future).  
\- \*\*Reason\*\*: keeping the model local

\*\*File Operations\*\*: Built-in \`os\`, custom wrappers around \`read\_file\` etc. tools.  
\- \*\*Reason\*\*: Direct sandbox integration.

\*\*Web Tools\*\*: Use provided \`web\_search\`, \`open\_page\_with\_find\`.  
\- \*\*Reason\*\*: Reliable, grounded.

\*\*Markdown Parsing\*\*: \`markdown\` or simple string processing.  
\- \*\*Reason\*\*: Lightweight.

\*\*Future Vector\*\*: \`chromadb\` or \`faiss\` (if embeddings available).  
\- Analysis: Only if needed for Q\&A scale.

\*\*No unnecessary libs\*\* \- keep minimal.

\#\# Step 5: Failure & Resilience Design

\*\*Failure Modes\*\*:  
1\. Tool rate limiting / blocks  
2\. LLM hallucination in synthesis  
3\. File corruption during edits  
4\. Infinite recursion / loop divergence  
5\. Poor quality web content  
6\. User abandons mid-process  
7\. Missing context in long researches  
8\. Tool output parsing errors  
9\. Resource exhaustion (memory for large info.md)

\*\*Mitigations\*\*:  
\- Exponential backoff retries  
\- Strict extraction prompts \+ critic verification  
\- timestemp-based editing \+ backups  
\- Convergence metrics \+ max iterations  
\- Multi-source validation  
\- Human review gates  
\- Chunking \+ summarization  
\- Structured JSON outputs for parsing  
\- Logging \+ graceful degradation

\*\*Monitoring\*\*: Log file size, iteration count, confidence averages.  
\*\*Logging\*\*: Timestamped entries in \`research\_log.md\`.  
\*\*Backup\*\*: Copy files before major edits.

\#\# Step 6: Development & Project Plan

\*\*Milestones\*\*:  
1\. \*\*Week 1\*\*: Core file system \+ Problem Clarifier \+ Basic Data Gatherer (1-2 iterations)  
2\. \*\*Week 2\*\*: Full recursive loop \+ Compactor \+ Anti-hallucination layers  
3\. \*\*Week 3\*\*: Hypothesis & Methodology modes \+ Finance/Startup specializations  
4\. \*\*Week 4\*\*: Q\&A, Polish, Testing on sample topics

\*\*Integration Points (High Risk)\*\*: Tool orchestration, Critic loop fidelity, File state management.

\*\*Testing Strategy\*\*:  
\- Unit: Prompt outputs, file ops  
\- Integration: End-to-end on sample research (e.g. "EV battery market 2026")  
\- Manual: Human audit for grounding/hallucinations  
\- Chaos: Simulate tool failures

\*\*AI Usage\*\*: Heavy for prompt engineering, initial drafts, critique. Manual for architecture, validation.

\*\*Code Review\*\*: Self-review \+ diff inspection.

\#\# Step 7: Deployment & Operations

\*\*CI/CD\*\*: Git \+ basic scripts (future).  
\*\*Environments\*\*: Local dev only initially.  
\*\*IaC\*\*: Docker Compose for dependencies.  
\*\*Scaling\*\*: Horizontal via multiple instances (future).  
\*\*Rollback\*\*: File versioning \+ git.

\#\# Step 8: Risk Register & Trade-offs

1\. \*\*Risk\*\*: Excessive tool usage leading to blocks (Likelihood: Medium, Impact: High)  
   \- Mitigation: Caching, smarter query prioritization and compacting after every 40k words/tokens

2\. \*\*Risk\*\*: Hallucination creep despite measures (Med, High)  
   \- Mitigation: Multi-layer verification. 

3\. \*\*Risk\*\*: Scope creep in recursive depth (High, Med)  
   \- Mitigation: Strict controls \+ user gates.

4\. \*\*Risk\*\*: Performance on local hardware (Med, Med)  
   \- Mitigation: Model tiering, chunking.

5\. \*\*Risk\*\*: Legal/web scraping issues (Low, High)  
   \- Mitigation: Respect robots.txt, ethical use, cite sources.

\*\*Trade-offs\*\*: Depth vs Speed; Local control vs Cloud power.

\---

\*\*Living Document\*\*: Update after each milestone. Next review: After Milestone 1\.

Specalized Modes:

- Startup Research  
- Financial Research

\*\*Financial Research\*\*:

The Financial Research mode is a specialized, high-precision workflow designed for deep analysis of stocks, companies, funds, or financial instruments. It follows the same core philosophy as the general research agent (grounding, recursion, verification, anti-hallucination) but with extra rigor around numbers, valuation metrics, financial statements, and causal reasoning.

\*\*Step 0: Problem & Scope Definition\*\*  

\- User provides the company/stock ticker(s), research goal (e.g., "Valuation of Reliance Industries", "Compare Tesla vs BYD", "Investment thesis for HDFC Bank"), and any specific focus areas (growth, risks, moats, etc.).  

\- The system creates or updates a dedicated section in \`problem.md\` for the financial research.  

\- User confirms the scope before proceeding.

\*\*Step 1: Initial Data Gathering (Broad Sweep)\*\*  

\- The system generates a comprehensive set of targeted search queries (e.g., "Reliance Industries latest quarterly results", "RELIANCE.NS valuation multiples 2026", "Reliance Industries annual report 2025 PDF", etc.).  

\- Uses \`web\_search\` \+ \`open\_page\_with\_find\` to fetch data from:

  \- Official company websites & investor relations pages

  \- Stock exchanges (NSE/BSE, NYSE, etc.)

  \- Financial data providers (Moneycontrol, Yahoo Finance, Screener.in, Bloomberg, etc.)

  \- Regulatory filings (SEBI, SEC EDGAR 10-K/10-Q)

  \- Analyst reports, news, and transcripts (with caution)

\*\*Step 2: Focused Extraction (The "Smaller AI" Reading Step)\*\*  

\- For every scraped webpage, the \*\*Focused Extractor\*\* (small/constrained model or tightly prompted LLM) reads the entire content and organizes data in \`info.md\`

\- It \*\*only extracts\*\*:

  \- Verbatim financial numbers and tables

  \- Key statements from management

  \- Valuation metrics (P/E, EV/EBITDA, ROE, etc.)

  \- Growth rates, margins, debt ratios, cash flow details

  \- Dates and context for every number

\- Every extracted item is stored in \`info.md\` with:

  \- Direct quote/excerpt

  \- Source URL \+ timestamp

  \- Confidence score

  \- Section/page reference

\*\*Step 3: Structured Financial Database Building\*\*  

\- The system organizes data in \`info.md\` under clear sections:

  \- Company Overview & Business Model

  \- Financial Statements (Income, Balance Sheet, Cash Flow) – historical \+ latest

  \- Key Ratios & Valuation Metrics (with 5-10 year trends where possible)

  \- Segment-wise Performance

  \- Management Commentary & Guidance

  \- Industry & Peer Comparison

  \- Risks & Contingencies

\*\*Step 4: Reasoning Audit & Blind Spot Detection\*\*  

This is the \*\*most important anti-hallucination layer\*\*:

\- A dedicated \*\*Reasoning Auditor\*\* (large model) analyzes all collected data and answers:

  \- Are all major valuation matrices explained? (Why is P/E high/low? What growth expectations justify it?)

  \- Are there any unreasoned anomalies? (Sudden jump in margins, debt spike, etc.)

  \- Are numbers consistent across sources?

  \- Is there data related to underlying companies or dependent sectors? 

  \- What key information is missing? (e.g., latest quarterly results, segment margins, promoter holding changes)

\- It explicitly lists \*\*Blind Spots\*\* and \*\*Unreasoned Claims\*\*.

\*\*Step 5: Recursive Deepening & Gap Filling\*\*  

\- Based on the auditor’s feedback, the system generates new targeted searches (top 5–8).  

\- Returns to Step 1–2–3 for new data.  

\- This \*\*critique → gather → update\*\* loop repeats \*\*until the auditor finds no major blind spots or unreasoned anomalies\*\*.  

\- Typical iterations: 4–8 cycles for a single company.

\*\*Step 6: Synthesis & Conclusion Layer\*\*  

\- Once gaps are closed, the system produces:

  \- Clean, well-structured summary of the company’s financial health

  \- Valuation assessment (Intrinsic value range, relative valuation)

  \- Investment Thesis (Bull case, Bear case, Base case)

  \- Key Risks with probability/impact

  \- Supporting evidence with direct links

\*\*Step 7: Multi-Company Comparison (if applicable)\*\*  

\- If user is comparing multiple companies, the system processes each one independently first, then runs a dedicated comparison module that highlights differences in metrics, business quality, and valuation.

\---

\#\#\# Key Anti-Hallucination Safeguards (Specific to Finance)

\- \*\*Strict Extraction Only\*\*: The Focused Extractor is forbidden from making interpretations or conclusions.

\- \*\*Source Grounding\*\*: Every claim in the final output must trace back to one or more sources in \`info.md\`.

\- \*\*Numbers Double-Checked\*\*: Important figures are verified across at least 2–3 independent sources.

\- \*\*Reasoning Audit\*\*: Explicit requirement that “why” behind every unusual number must be explained with evidence.

\- \*\*Versioned Updates\*\*: All changes to \`info.md\` are logged with diffs.

\- \*\*Confidence Scoring\*\*: Low-confidence data is clearly flagged.

\- \*\*Human Review Gate\*\*: User can review \`info.md\` at any point and request more depth.

\---

\#\#\# Integration with Overall System

\- Financial research feeds into \*\*Hypothesis mode\*\* (e.g., "Is this stock undervalued?") and \*\*Methodology/Ideas mode\*\* (e.g., investment strategy or startup competitive analysis).

\- All data remains available for future vector search / Q\&A.

\- The process is fully traceable — you can always go back to raw sources.

\---

\#\#\# \*\* Startup Researcher Mode \*\*

The \*\*Startup Researcher\*\* is a specialized workflow designed for deep market intelligence, opportunity discovery, and idea validation. It helps users explore new business ideas, validate market needs, identify niches, and generate testable startup concepts.

It follows the same core principles as the overall system (\*\*grounding, recursion, verification, anti-hallucination\*\*) but is tailored for:

\- Market sizing & trends

\- Customer pain points

\- Competitive landscape

\- Emerging opportunities

\- Idea generation \+ validation strategies

\---

\#\#\# Complete Step-by-Step Process

\*\*Step 0: Problem & Scope Definition\*\*  

\- User provides the startup idea, industry, target market, or broad goal (e.g., "EdTech startup in India", "Sustainable packaging solutions", "AI tools for small retailers").  

\- The system creates or updates a dedicated section in \`problem.md\`.  

\- It breaks the high-level goal into specific research angles (market size, user segments, competitors, trends, etc.).  

\- User reviews and confirms the scope.

\*\*Step 1: Initial Data Gathering (Broad Market Sweep)\*\*  

\- The system generates dozens of targeted search queries across categories:

  \- Market size & growth forecasts

  \- Customer segments & pain points

  \- Competitor analysis

  \- Regulatory & technology trends

  \- Recent funding/news in the space

\- Uses \`web\_search\` \+ \`open\_page\_with\_find\` to pull data from:

  \- Industry reports (Statista, McKinsey, Gartner, etc.)

  \- Government data & surveys

  \- Startup databases (Crunchbase, Tracxn, PitchBook)

  \- News, forums (Reddit, Product Hunt), academic papers

  \- Competitor websites & annual reports

\*\*Step 2: Focused Extraction (The "Smaller AI" Reading Step)\*\*  

\- For every scraped page, the \*\*Focused Extractor\*\* carefully reads the full content.  

\- It extracts \*\*only\*\* relevant grounded information such as:

  \- Market size numbers and growth rates (with years and sources)

  \- Customer quotes, survey results, or stated pain points

  \- Competitor features, pricing, funding amounts

  \- Emerging trends and supporting evidence

  \- Regulatory changes or barriers

\- Every extraction is saved in \`info.md\` with:

  \- Verbatim quote/excerpt

  \- Source URL \+ timestamp

  \- Context (e.g., “India EdTech market 2025 projection”)

  \- Confidence score

\*\*Step 3: Structured Market Knowledge Base\*\*  

The system organizes data in \`info.md\` into clear sections:

\- Market Overview & Sizing (TAM, SAM, SOM)

\- Customer Personas & Pain Points

\- Competitive Landscape (direct & indirect competitors)

\- Trends & Technological Shifts

\- Regulatory & Economic Factors

\- Funding & Exit Patterns

\- Open Questions / Data Gaps

\*\*Step 4: Market Niche & Opportunity Discovery\*\*  

\- The system identifies \*\*potential market niches\*\* by analyzing gaps in the data (underserved segments, unmet needs, friction points).  

\- It generates an initial list of 8–15 possible niches/opportunities.

\*\*Step 5: Recursive Deepening & Gap Filling\*\*  

\- A \*\*Critique & Opportunity Auditor\*\* reviews the collected data and lists:

  \- Blind spots (missing data on specific customer segments, regional differences, etc.)

  \- Weak evidence areas

  \- Promising but under-researched niches

\- Based on this, the system generates new targeted searches and returns to Steps 1–2.  

\- This \*\*gather → audit → deepen\*\* loop repeats \*\*4–8 times\*\* until the auditor is satisfied that major opportunities are well-supported and blind spots are minimized.

\*\*Step 6: Hypothesis / Market Need Formulation\*\*  

\- The system produces a refined set of \*\*Market Niches & Hypotheses\*\* in \`niches.md\` or \`hypotheses.md\`, with:

  \- Clear description of the niche/need

  \- Supporting evidence (with citations)

  \- Estimated market potential

  \- Key assumptions & risks

  \- Strength rating (based on evidence quality)

\*\*Step 7: Idea Generation & Testing Strategy\*\*  

\- For each promising niches (or user-selected ones), the system generates:

  \- Multiple startup ideas / product concepts

  \- Go-to-market approaches

  \- Possible MVP features

\- It then designs \*\*validation tests\*\* for each idea:

  \- Landing page tests

  \- Survey/interview scripts

  \- Smoke tests / fake door tests

  \- Competitor benchmarking

  \- Pilot programs

\- Each idea/test includes success metrics and risk assessment.

\*\*Step 8: Final Synthesis & Recommendations\*\*  

\- Produces a comprehensive Startup Research Report containing:

  \- Top recommended niches

  \- Prioritized ideas with validation plans

  \- Overall market attractiveness

  \- Key risks & mitigation suggestions

  \- All source links for traceability

\---

\#\#\# Key Anti-Hallucination Safeguards (Specific to Startup Research)

\- \*\*Strict Extraction\*\*: Focused Extractor never invents market numbers or customer insights.

\- \*\*Evidence Weighting\*\*: Niches and ideas are ranked based on strength and quantity of supporting sources.

\- \*\*Assumption Flagging\*\*: Every hypothesis clearly lists what is assumed vs. evidenced.

\- \*\*Multi-Source Validation\*\*: Important claims (e.g., market size) require 2–3 independent sources.

\- \*\*Critic Layer\*\*: A separate critique step challenges optimistic interpretations and demands evidence.

\- \*\*Living Document\*\*: \`info.md\` remains the single source of truth — all conclusions link back to it.

\- \*\*Human Review Points\*\*: User can inspect \`info.md\`, niches, and ideas at any stage.

\---

\#\#\# Integration with Overall System

\- Startup Researcher heavily uses the general \*\*Data Gatherer\*\* loop.

\- It feeds directly into \*\*Hypothesis mode\*\* and \*\*Methodology/Ideas mode\*\*.

\- All research is saved persistently, so you can later run Q\&A against the vector-searchable knowledge base.

\- Can be combined with \*\*Financial Research\*\* (e.g., analyze competitors’ financials while doing market research).

\---

This mode transforms vague startup ideas into \*\*evidence-based, de-risked opportunities\*\* through systematic, recursive research.

\---

Future upgrades : 

Needs to set it up in personal MCP server so that I can use it with other projects 

Need to make it modular for API

