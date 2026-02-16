import os
import re
import pdfplumber
from gtts import gTTS
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime
import traceback

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

def generate_audio(insights):
    """Generate comprehensive audio summary"""
    summary_parts = []
    
    summary_parts.append("Here is a summary of the research report.")
    
    # Policy Decisions
    if insights["policy_decisions"]:
        summary_parts.append("Policy decisions.")
        summary_parts.extend(insights["policy_decisions"][:3])
    
    # Executive Summary
    if insights["executive_summary"]:
        summary_parts.append("Key highlights.")
        summary_parts.extend(insights["executive_summary"][:3])
    
    # Forecasts
    if insights["forecasts"]:
        summary_parts.append("Forecasts and projections.")
        summary_parts.extend(insights["forecasts"][:3])
    
    # Market Outlook
    if insights["market_outlook"]:
        summary_parts.append("Market outlook.")
        summary_parts.extend(insights["market_outlook"][:2])
    
    # Key Findings
    if insights["key_findings"]:
        summary_parts.append("Key findings.")
        summary_parts.extend(insights["key_findings"][:3])
    
    # Conclusions
    if insights["conclusions"]:
        summary_parts.append("Conclusions.")
        summary_parts.extend(insights["conclusions"][:2])
    
    # Join and clean for speech
    summary = " ".join(summary_parts)
    summary = summary.replace('%', ' percent ')
    summary = summary.replace('₹', ' rupees ')
    summary = summary.replace('Rs', ' rupees')
    summary = summary.replace('bps', ' basis points')
    summary = summary.replace('FY', ' financial year ')
    
    # Generate audio
    audio_path = os.path.join(AUDIO_FOLDER, "summary.mp3")
    
    try:
        tts = gTTS(summary, lang="en", tld="co.uk")
        tts.save(audio_path)
        return "/static/audio/summary.mp3"
    except Exception as e:
        print(f"Audio error: {e}")
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
            
            data = extract_insights(raw_text)
            
            # Print extraction stats
            total_insights = sum(len(v) for v in data.values())
            print(f"✅ Extracted {total_insights} total insights:")
            for category, items in data.items():
                if items:
                    print(f"   - {category}: {len(items)} items")
            
            # Generate audio if content exists
            if any(data.values()):
                audio_file = generate_audio(data)
            
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