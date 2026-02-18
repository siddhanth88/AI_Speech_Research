import os
import re
import json
import traceback

import pdfplumber
import requests
from gtts import gTTS
from flask import Flask, render_template, request, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime

app = Flask(__name__)

UPLOAD_FOLDER = 'uploads'
AUDIO_FOLDER = 'static/audio'
ALLOWED_EXTENSIONS = {'pdf'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(AUDIO_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def extract_pdf_text(pdf_path):
    """Extract text with proper line joining - PROCESS ALL PAGES"""
    text = ""
    
    with pdfplumber.open(pdf_path) as pdf:
        # Process ALL pages to capture complete content
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                # Fix hyphenated line breaks
                page_text = re.sub(r'-\n', '', page_text)
                
                # Join broken sentences
                lines = page_text.split('\n')
                joined = ""
                current = ""
                
                for line in lines:
                    line = line.strip()
                    if not line:
                        continue
                    
                    # Complete sentence
                    if line[-1] in '.!?':
                        current += " " + line if current else line
                        joined += current + " "
                        current = ""
                    else:
                        current += " " + line if current else line
                
                if current:
                    joined += current + " "
                
                text += joined
    
    return text


def build_strategy_evidence(text):
    """
    Scan the entire extracted PDF text and build a compact, high-signal evidence
    set for the LLM. This avoids token overruns while still reflecting the full
    document.
    """
    # Normalize whitespace early
    text = re.sub(r"\s+", " ", text).strip()

    # Split into sentence-like chunks
    sentences = re.split(r"(?<=[.!?])\s+", text)

    keywords = [
        # Flows / positioning
        "retail", "sip", "flows", "flow", "inflows", "outflows", "positioning",
        # Estimates / fundamentals
        "earnings", "eps", "revenue", "sales", "margin", "margins", "guidance",
        "estimate", "estimates", "revision", "revisions", "cut", "cuts", "raise", "raised",
        "downgrade", "upgrade", "consensus",
        # Valuation / pricing
        "valuation", "valuations", "multiple", "p/e", "pe ", "p/b", "pb ", "ev/ebitda", "rerating",
        "fair value", "target price", "tp ", "price target", "multiple compression",
        "dislocation", "disconnect", "dispersion", "compression",
        # Risks / credibility
        "execution", "credibility", "visibility", "pipeline", "risk", "drawdown",
        # Forward-looking
        "forward", "outlook", "looking ahead", "ahead", "scenario", "base case",
    ]

    def is_high_signal(s):
        sl = s.lower()
        if len(s) < 40:
            return False
        if any(k in sl for k in keywords):
            return True
        # numeric / valuation evidence
        if re.search(r"\d", s) and re.search(r"(%|percent|bps|basis|₹|rs\.?|\$|usd|crore|lakh|billion|million|trillion|x\b)", sl):
            return True
        return False

    picked = []
    seen = set()
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if not is_high_signal(s):
            continue
        # Deduplicate on lowercase prefix to keep variety
        key = s.lower()[:120]
        if key in seen:
            continue
        seen.add(key)
        picked.append(s)
        if len(picked) >= 140:
            break

    # If the doc is sparse, fall back to the first portion so we still have context
    if len(picked) < 25:
        picked = [s for s in sentences[:80] if len(s.strip()) >= 30]

    evidence = "\n".join(f"- {s}" for s in picked)
    return evidence

def is_boilerplate(text):
    """Filter out ONLY obvious disclaimers - more lenient"""
    # Only exclude if it contains multiple disclaimer keywords
    junk_keywords = [
        'registered office', 'compliance officer', 'sebi registration',
        'all rights reserved', 'copyright', 'reproduction'
    ]
    
    text_lower = text.lower()
    match_count = sum(1 for keyword in junk_keywords if keyword in text_lower)
    
    # Only exclude if multiple disclaimer keywords present
    return match_count >= 2

def is_table_garbage(sentence):
    """More lenient table filtering - only remove obvious garbage"""
    # Allow longer sentences (increased from 250 to 400)
    if len(sentence) > 400:
        return True
    
    # Only flag as garbage if LOTS of numbers (increased from 15 to 25)
    if len(re.findall(r'\d', sentence)) > 25:
        return True
    
    # Check for obvious table fragments (5+ consecutive numbers)
    if re.search(r'\d+\s+\d+\s+\d+\s+\d+\s+\d+', sentence):
        return True
    
    return False

def clean_sentence(sentence):
    """Clean and format sentence - PRESERVE MORE CONTENT"""
    # Keep brackets for important context like (RBI) or (FY25)
    # Only remove empty brackets or very long ones
    sentence = re.sub(r'\(\s*\)', '', sentence)
    sentence = re.sub(r'\([^)]{100,}\)', '', sentence)  # Only remove very long bracketed content
    
    # Normalize whitespace
    sentence = re.sub(r'\s+', ' ', sentence)
    
    # Minimal replacements - keep most original text
    replacements = {
        "the rbi has": "RBI has",
        "rbi mpc": "RBI MPC",
        " rbi ": " RBI ",
        " gdp ": " GDP ",
        " cpi ": " CPI ",
        " fy ": " FY ",
    }
    
    for k, v in replacements.items():
        sentence = sentence.replace(k, v)
        sentence = sentence.replace(k.upper(), v)
    
    sentence = sentence.strip()
    
    # Capitalize first letter if not already
    if sentence and sentence[0].islower():
        sentence = sentence[0].upper() + sentence[1:]
    
    return sentence

def extract_insights(text):
    """COMPREHENSIVE extraction with LESS filtering"""
    
    insights = {
        "executive_summary": [],
        "key_findings": [],
        "data_points": [],
        "market_outlook": [],
        "policy_decisions": [],
        "forecasts": [],
        "conclusions": []
    }
    
    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    
    for s in sentences:
        s = s.strip()
        
        # More lenient minimum length (reduced from 40 to 25)
        if len(s) < 25:
            continue
        
        # Skip only obvious boilerplate
        if is_boilerplate(s):
            continue
            
        # Skip only obvious table garbage
        if is_table_garbage(s):
            continue
        
        # Clean
        cleaned = clean_sentence(s)
        
        # More lenient length restrictions (min 20, max 500)
        if len(cleaned) < 20 or len(cleaned) > 500:
            continue
        
        # Skip duplicates across all categories
        is_duplicate = False
        for category in insights.values():
            if cleaned in category:
                is_duplicate = True
                break
        
        if is_duplicate:
            continue
        
        # Categorize with broader matching
        s_lower = s.lower()
        
        # Policy Decisions (NEW CATEGORY)
        if re.search(r'(unanimously|decided|maintained|retained|raised|cut|reduced|repo rate|policy rate|stance)', s_lower):
            insights["policy_decisions"].append(cleaned)
        
        # Forecasts & Projections (NEW CATEGORY)
        elif re.search(r'(fy\d+|forecast|project|estimate|expect.*fy|growth.*\d+.*%)', s_lower):
            insights["forecasts"].append(cleaned)
        
        # Market Outlook (NEW CATEGORY)
        elif re.search(r'(outlook|view|going forward|ahead|future|trend|trajectory)', s_lower):
            insights["market_outlook"].append(cleaned)
        
        # Executive Summary (top highlights)
        elif re.search(r'(key|important|significant|major|notable|highlight)', s_lower):
            insights["executive_summary"].append(cleaned)
        
        # Key Findings (broader matching)
        elif re.search(r'(likely|will|believes?|suggests?|indicates?|shows?|reveals?)', s_lower):
            insights["key_findings"].append(cleaned)
        
        # Data Points (numbers with context - EXPANDED)
        elif re.search(r'\d+(\.\d+)?\s?(%|percent|bps|basis points|₹|rs\.?|usd|\$|crore|lakh|billion|million|trillion)', s_lower):
            insights["data_points"].append(cleaned)
        
        # Conclusions (broader matching)
        elif re.search(r'(overall|summary|therefore|conclude|thus|hence|consequently)', s_lower):
            insights["conclusions"].append(cleaned)
        
        # Catch remaining important content
        elif len(cleaned) > 40 and any(word in s_lower for word in ['inflation', 'growth', 'economy', 'market', 'sector', 'industry']):
            insights["key_findings"].append(cleaned)
    
    # Increase limits significantly (from 8 to 15)
    for key in insights:
        insights[key] = insights[key][:15]
    
    return insights


def generate_market_outlook_summary(report_text):
    """
    Use an LLM (via Groq API) to transform the raw report text into a highly
    structured, valuation-relevant equity research outlook plus an audio-ready
    script. The function expects GROQ_API_KEY to be set in the env.
    """
    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GROQ_API_KEY environment variable is not set. "
            "Set it to your Groq API key to enable the Market Outlook analyzer."
        )

    # Build a compact evidence pack from the *entire* document so we can stay
    # within Groq token limits while still reflecting the full PDF.
    evidence = build_strategy_evidence(report_text)

    system_prompt = """
You are a senior institutional equity strategist and valuation analyst.
You are analyzing a full professional research report.
Your objective is to synthesize the ENTIRE document into a high-conviction, investment-committee-grade briefing.
Think like a sell-side strategist presenting to portfolio managers.

STRICT RULES:
1. Identify the CENTRAL THESIS of the report in one sharp sentence.
2. Detect and quantify (ONLY if explicitly stated):
   - EPS revisions
   - Revenue revisions
   - Margin guidance changes
   - Multiple changes
   - Fair value / target price revisions
3. Explicitly assess:
   - Execution risk
   - Valuation compression risk
   - Flow sensitivity risk
   - Estimate credibility risk
4. Remove duplication.
5. Eliminate generic commentary.
6. Avoid weak language such as: "may impact sentiment", "could affect", "important to monitor".
7. Do NOT give textbook advice (e.g., diversification).
8. Do NOT hallucinate numbers not present in the report.

Every bullet MUST:
- Introduce new information
- Include a valuation or market implication (why it matters)
- Be analytical, not descriptive

OUTPUT STRUCTURE (return as JSON fields):
SECTION 1 — Central Thesis (1 sentence max)
SECTION 2 — Estimate & Valuation Reset (3–4 bullets; fewer if not supported)
Focus strictly on:
- EPS revisions / revenue revisions / margin changes / multiple changes / fair value implications
SECTION 3 — Structural & Execution Risk (max 3 bullets)
Each bullet MUST start with a risk label: "Elevated:", "Moderate:", or "Contained:"
SECTION 4 — Market Vulnerability Assessment
Return levels exactly as Low / Moderate / High and a score X/10:
- Earnings Risk Level
- Valuation Compression Risk
- Flow Sensitivity Risk
- Overall Vulnerability Score
SECTION 5 — Strategic Investment Stance (2–3 sentences max)
Use one of: Constructive / Neutral / Cautious / Defensive. Explain what must change for re-rating.

Tone: Authoritative, institutional, high conviction, concise. No filler. No repetition. No macro template unless directly valuation-relevant.

Return ONLY valid JSON with this exact structure and nothing else:
{
  "central_thesis": "one sentence",
  "estimate_valuation_reset": ["bullet 1", "bullet 2", "bullet 3", "bullet 4"],
  "structural_execution_risk": ["Elevated: ...", "Moderate: ...", "Contained: ..."],
  "market_vulnerability_assessment": {
    "earnings_risk_level": "Low|Moderate|High",
    "valuation_compression_risk": "Low|Moderate|High",
    "flow_sensitivity_risk": "Low|Moderate|High",
    "overall_vulnerability_score": 0
  },
  "strategic_investment_stance": "2-3 sentences",
  "audio_script": "Audio-ready script (<= ~2.5 minutes) that narrates the full briefing in a natural institutional tone."
}

If a field lacks material report-backed content, keep it short/blank rather than filling with generic language.
"""

    payload = {
        # Groq exposes an OpenAI-compatible Chat Completions API.
        # Use a currently supported general-purpose Llama model.
        "model": "llama-3.3-70b-versatile",
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    "Below is an evidence pack extracted from the full strategy report. "
                    "Apply the above instructions strictly and return ONLY the JSON object.\n\n"
                    f"{evidence}"
                ),
            },
        ],
        "temperature": 0.2,
        # Ask the model to return strict JSON; Groq supports OpenAI-style response_format.
        "response_format": {"type": "json_object"},
    }

    try:
        response = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=90,
        )
    except requests.RequestException as exc:
        raise RuntimeError(f"Failed to contact Groq API: {exc}") from exc

    # Handle HTTP errors (including 429 rate limits) explicitly
    if response.status_code == 429:
        raise RuntimeError(
            "Groq API rate limit or quota exceeded. "
            "Please wait a bit and try again, or use a different API key / account."
        )

    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        # Surface a concise error for other HTTP failures
        raise RuntimeError(
            f"Groq API returned an error ({response.status_code}): {response.text[:300]}"
        ) from exc
    content = response.json()["choices"][0]["message"]["content"].strip()

    # Parse JSON returned by the model
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        # Fallback: try to extract the first top-level JSON object from the text
        start = content.find("{")
        end = content.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                data = json.loads(content[start : end + 1])
            except json.JSONDecodeError as exc:
                raise RuntimeError("Model output was not valid JSON. Please try again.") from exc
        else:
            raise RuntimeError("Model output was not valid JSON. Please try again.")

    # Normalise expected fields
    def _strip_index_names(s):
        sl = s.lower()
        if "nifty" in sl or "sensex" in sl:
            return ""
        return s.strip()

    data["central_thesis"] = _strip_index_names(str(data.get("central_thesis", "") or ""))

    list_keys = ["estimate_valuation_reset", "structural_execution_risk"]
    for key in list_keys:
        value = data.get(key, [])
        if not isinstance(value, list):
            value = [str(value)]
        cleaned = []
        for item in value:
            t = _strip_index_names(str(item))
            if t:
                cleaned.append(t)
        data[key] = cleaned

    mva = data.get("market_vulnerability_assessment", {}) or {}
    if not isinstance(mva, dict):
        mva = {}
    data["market_vulnerability_assessment"] = {
        "earnings_risk_level": str(mva.get("earnings_risk_level", "Moderate")),
        "valuation_compression_risk": str(mva.get("valuation_compression_risk", "Moderate")),
        "flow_sensitivity_risk": str(mva.get("flow_sensitivity_risk", "Moderate")),
        "overall_vulnerability_score": mva.get("overall_vulnerability_score", 5),
    }

    data["strategic_investment_stance"] = _strip_index_names(
        str(data.get("strategic_investment_stance", "") or "")
    )

    audio_script = data.get("audio_script", "")
    if isinstance(audio_script, list):
        audio_script = " ".join(str(x) for x in audio_script)
    data["audio_script"] = _strip_index_names(str(audio_script or ""))

    return data

def generate_market_outlook_audio(summary_dict):
    """
    Generate a spoken macro market outlook from the structured JSON output
    using gTTS. This is tailored to the 5-section committee format.
    """
    # Prefer the model-crafted audio script when available
    text = (summary_dict.get("audio_script") or "").strip()

    # Fallback: build a script from bullets if audio_script is missing
    if not text:
        sections_order = [
            ("market_outlook_executive", "Executive earnings and valuation view."),
            ("positive_drivers", "Key positive drivers for earnings and valuation."),
            ("key_risks", "Key risks to earnings, margins, and valuation."),
            ("what_matters_most", "What matters most and could change the base case."),
            ("strategic_conclusion", "Strategic conclusion and stance."),
        ]

        parts = [
            "Here is a concise, valuation-focused research summary for the investment committee."
        ]

        for key, heading in sections_order:
            items = summary_dict.get(key) or []
            if not items:
                continue
            parts.append(heading)
            # Keep audio concise: at most 6 bullets per section
            for bullet in items[:6]:
                parts.append(bullet)

        text = " ".join(parts)

    # Clean a few symbols so TTS sounds natural
    text = text.replace("%", " percent ")
    text = text.replace("bps", " basis points")
    text = text.replace("Rs", " rupees")
    text = text.replace("₹", " rupees ")
    text = text.replace("FY", " financial year ")

    audio_path = os.path.join(AUDIO_FOLDER, "market_outlook_summary.mp3")

    try:
        tts = gTTS(text, lang="en", tld="co.uk")
        tts.save(audio_path)
        return "/static/audio/market_outlook_summary.mp3"
    except Exception as exc:
        print(f"Audio generation error: {exc}")
        return None

@app.route("/", methods=["GET", "POST"])
def index():
    data = None
    audio_file = None
    
    if request.method == "POST":
        try:
            if 'pdf' not in request.files:
                return render_template("index.html", error="No file uploaded")
            
            pdf = request.files["pdf"]
            
            if pdf.filename == '':
                return render_template("index.html", error="No file selected")
            
            if not allowed_file(pdf.filename):
                return render_template("index.html", error="Only PDF files allowed")
            
            # Save PDF
            filename = secure_filename(pdf.filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            pdf_path = os.path.join(UPLOAD_FOLDER, f"{timestamp}_{filename}")
            pdf.save(pdf_path)
            
            print(f"📄 Processing: {filename}")
            
            # Extract and analyze
            raw_text = extract_pdf_text(pdf_path)
            print(f"📝 Extracted {len(raw_text)} characters from PDF")

            # Use LLM to generate the macro Market Outlook structure
            data = generate_market_outlook_summary(raw_text)

            # Generate audio if we got any bullets back
            if data:
                try:
                    audio_file = generate_market_outlook_audio(data)
                except Exception as exc:
                    print(f"Failed to generate audio: {exc}")
            
            # Cleanup
            try:
                os.remove(pdf_path)
            except:
                pass
            
            print("✅ Analysis complete!")
            
        except Exception as e:
            print(f"❌ Error: {e}")
            traceback.print_exc()
            return render_template("index.html", error=str(e))
    
    return render_template("index.html", data=data, audio=audio_file)

@app.route("/test")
def test():
    return jsonify({'status': 'OK', 'service': 'Research Paper Analyzer'})

if __name__ == "__main__":
    print("="*60)
    print("📊 Research Paper Analyzer - IMPROVED VERSION")
    print("="*60)
    print("✅ Processes ALL pages (not just 70%)")
    print("✅ Less aggressive filtering")
    print("✅ More categories for better organization")
    print("✅ Captures up to 15 items per category")
    print("="*60)
    
    port = int(os.environ.get('PORT', 5000))
    app.run(debug=True, host='0.0.0.0', port=port)