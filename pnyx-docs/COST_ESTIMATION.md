# Cost Estimation Analysis

**Product:** Meeting Co-Pilot (Pnyx)
**Date:** Jan 30, 2026
**Currency:** USD

This document breaks down the estimated infrastructure and API costs for running Meeting Co-Pilot. The architecture relies on "Serverless" and "Pay-As-You-Go" models, meaning costs scale linearly with usage.

---

## 1. Unit Cost Analysis (Per 1-Hour Meeting)

This is the variable cost to process a single 60-minute meeting.

| Component | Service | Unit Price | Cost per 1h Meeting | Notes |
| :--- | :--- | :--- | :--- | :--- |
| **Transcription** | **Groq API** (Whisper v3) | $0.111 / hour | **$0.11** | Extremely fast & cheap. |
| **Diarization** | **Deepgram** (Nova-2) | $0.0063 / min | **$0.38** | Includes Speaker ID add-on. |
| **AI Summary** | **Gemini 1.5 Flash** | $0.075 / 1M tokens | **$0.001** | ~12k tokens context. Negligible. |
| **AI Chat (10 Qs)**| **Gemini 1.5 Flash** | $0.075 / 1M tokens | **$0.012** | ~150k tokens total context. |
| **Web Search (2)** | **SerpAPI** | $0.025 / search | **$0.05** | Optional feature. |
| **Storage** | **GCP Bucket** | $0.02 / GB / mo | **$0.002** | 1h WAV (16kHz) ≈ 115MB. |
| **Total** | | | **~$0.55** | **Per Meeting** |

---

## 2. Monthly Infrastructure Costs (Fixed/Base)

These costs apply regardless of how many meetings you process (up to a limit).

| Service | Tier | Monthly Cost | Notes |
| :--- | :--- | :--- | :--- |
| **Database** | **Neon (Postgres)** | **Free** | Up to 10GB storage (enough for ~500k meetings metadata). |
| **Frontend** | **Vercel** | **Free** | Hobby tier is sufficient for internal tools. |
| **Backend** | **Google Cloud Run** | **~$5.00** | Est. CPU/RAM usage. Free tier covers first 180k vCPU-seconds. |
| **Search** | **SerpAPI** | **$25.00** | Minimum paid tier (1,000 searches). Free tier available (250 searches). |
| **Total** | | **~$30.00** | Mostly SerpAPI subscription. |

> 💡 **Tip:** If you stay within SerpAPI's free tier (250 searches/mo) and Cloud Run's free tier, the fixed cost is effectively **$0**.

---

## 3. Total Cost Scenarios

### Scenario A: Small Team (Startup)
*   **Usage:** 40 meetings / month (10 per week).
*   **Avg Duration:** 1 hour.

| Category | Calculation | Cost |
| :--- | :--- | :--- |
| **Variable** | 40 meetings * $0.55 | $22.00 |
| **Fixed** | Cloud Run + SerpAPI (Starter) | $30.00 |
| **Total Monthly** | | **$52.00** |
| **Cost per User** | Assuming 5 users | **$10.40 / user** |

### Scenario B: Power Users / Agency
*   **Usage:** 200 meetings / month (50 per week).
*   **Avg Duration:** 1 hour.

| Category | Calculation | Cost |
| :--- | :--- | :--- |
| **Variable** | 200 meetings * $0.55 | $110.00 |
| **Fixed** | Cloud Run + SerpAPI (Starter) | $30.00 |
| **Total Monthly** | | **$140.00** |
| **Cost per Meeting** | | **$0.70** |

---

## 4. Component Deep Dive

### A. Google Cloud Storage (`pnyx-recordings`)
*   **Pricing:** Standard Storage in `us-central1` is **$0.02 per GB/month**.
*   **Data Size:**
    *   Format: 16kHz Mono WAV.
    *   Rate: ~32 KB/s ≈ 115 MB/hour.
*   **Example:**
    *   100 meetings (100 hours) = 11.5 GB.
    *   **Cost:** 11.5 * $0.02 = **$0.23 / month**.
    *   *Conclusion:* Storage is practically free.

### B. Groq (Transcription)
*   **Model:** `whisper-large-v3`
*   **Rate:** $0.111 per hour.
*   **Comparison:** OpenAI Whisper API is ~$0.36/hour. Groq is **3x cheaper** and much faster.

### C. Deepgram (Diarization)
*   **Model:** Nova-2 ($0.0043/min) + Diarization ($0.002/min).
*   **Optimization:** You could switch to `whisper-large-v3-turbo` on Groq + Pyannote (Local Diarization) to cut this cost to near zero, but it requires heavy GPU on the backend (expensive hosting). Deepgram is the cost-effective "Serverless" choice.

### D. Google Gemini (Intelligence)
Pricing is per **1 million tokens** (approx. 4M characters), split by context window size.

| Model | Input Cost (per 1M) | Output Cost (per 1M) | Context (Tokens) | Use Case |
| :--- | :--- | :--- | :--- | :--- |
| **Gemini 1.5 Flash** | **$0.075** | **$0.30** | 128k (Fast) | **Default:** Summaries, Chat, Search. |
| **Gemini 1.5 Flash-8B**| **$0.0375** | **$0.15** | 1M (Cheapest) | Simple tasks, high volume. |
| **Gemini 1.5 Pro** | **$1.25** | **$5.00** | 2M (Smartest) | Complex reasoning, deep analysis. |

*   **Average Meeting Cost (Flash):** ~12k tokens = **$0.001**.
*   **Average Meeting Cost (Pro):** ~12k tokens = **$0.015**.
*   *Conclusion:* Even with the Pro model, AI costs are very low per meeting compared to diarization.

### E. Server (Cloud Run)
*   **Configuration:** 1 vCPU, 2GB RAM.
*   **Scaling:** Scales to zero when not in use.
*   **Processing:**
    *   Migration/Upload: ~10s per meeting.
    *   Diarization Wait: ~30s per meeting.
    *   Chat: ~2s per request.
*   **Free Tier:** Google offers 2M requests and 180k vCPU-seconds free per month.
*   **Impact:** Most small deployments will pay **$0** for compute.

---

## 5. Cost Optimization Strategy

To reduce costs further:

1.  **Diarization:** Deepgram is the biggest cost driver (~70%).
    *   *Option:* Use a purely local VAD+Clustering approach on the backend (free CPU/RAM) instead of Deepgram. Accuracy drops, but cost drops by $0.38/meeting.
2.  **Search:** SerpAPI is expensive ($25/mo base). We recommend switching to **Tavily** or **Brave**.
    *   **Tavily:** **$8 / 1k searches**. 1,000 free searches/month. Optimized for RAG (faster, no scraping needed).
    *   **Brave Search:** **$5 / 1k searches**. 2,000 free searches/month. Cheapest for raw links.
    *   *Impact:* Switching to Tavily's free tier saves the $25/mo fixed cost immediately.
3.  **Storage Lifecycle:**
    *   Set a GCP Lifecycle Rule to delete recordings after 30 days.
    *   *Impact:* Keeps storage usage flat, capping cost at <$1/mo.
