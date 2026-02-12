import os
import re
import pdfplumber
from gtts import gTTS
from flask import Flask, render_template, request, send_file, jsonify
from werkzeug.utils import secure_filename
from datetime import datetime
import traceback

app = Flask(__name__)

# Configuration
UPLOAD_FOLDER = 'uploads'
OUTPUT_FOLDER = 'outputs'
ALLOWED_EXTENSIONS = {'pdf'}

os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
app.config['OUTPUT_FOLDER'] = OUTPUT_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def clean_text(text):
    """Clean text for better speech"""
    text = re.sub(r'\s+', ' ', text)
    text = text.replace('- ', '')
    
    abbreviations = {
        'Dr.': 'Doctor', 'Mr.': 'Mister', 'Mrs.': 'Missus', 'Ms.': 'Miss',
        'Prof.': 'Professor', 'etc.': 'etcetera', 'e.g.': 'for example',
        'i.e.': 'that is', 'vs.': 'versus', 'Fig.': 'Figure',
    }
    for abbr, full in abbreviations.items():
        text = text.replace(abbr, full)
    
    # Remove citations
    text = re.sub(r'\[[\d,\s-]+\]', '', text)
    text = re.sub(r'\([\w\s,\.]+\d{4}[a-z]?\)', '', text)
    text = re.sub(r'http[s]?://\S+', '', text)
    
    return text.strip()

def extract_text_from_pdf(pdf_path):
    """Extract text from PDF"""
    print(f"Extracting text from: {pdf_path}")
    text = ""
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                text += page_text + " "
    print(f"Extracted {len(text)} characters")
    return text.strip()

def text_to_speech(text, output_file):
    """
    Convert text to speech using Google TTS
    """
    print(f"Generating audio with gTTS to: {output_file}")
    
    try:
        # Create gTTS object
        tts = gTTS(text=text, lang='en', slow=False)
        
        # Save to file
        tts.save(output_file)
        
        print(f"Audio generated successfully!")
        return True
        
    except Exception as e:
        print(f"gTTS Error: {str(e)}")
        raise

def process_pdf(pdf_path, output_filename):
    """Main processing function"""
    try:
        # Extract text
        print("Step 1: Extracting text...")
        raw_text = extract_text_from_pdf(pdf_path)
        if not raw_text or len(raw_text) < 10:
            raise ValueError("No text found in PDF")
        
        # Clean text
        print("Step 2: Cleaning text...")
        cleaned_text = clean_text(raw_text)
        
        # Limit text length
        max_chars = 50000
        if len(cleaned_text) > max_chars:
            print(f"Warning: Text too long ({len(cleaned_text)} chars), truncating to {max_chars}")
            cleaned_text = cleaned_text[:max_chars] + "..."
        
        # Generate audio
        print("Step 3: Generating audio...")
        final_output = os.path.join(app.config['OUTPUT_FOLDER'], output_filename)
        
        text_to_speech(cleaned_text, final_output)
        
        print(f"SUCCESS! Output saved to: {final_output}")
        return final_output
    
    except Exception as e:
        print(f"ERROR: {str(e)}")
        print(traceback.format_exc())
        raise

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/upload', methods=['POST'])
def upload_file():
    print("\n=== NEW UPLOAD REQUEST ===")
    
    try:
        if 'file' not in request.files:
            return jsonify({'error': 'No file uploaded'}), 400
        
        file = request.files['file']
        print(f"File received: {file.filename}")
        
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400
        
        if not allowed_file(file.filename):
            return jsonify({'error': 'Only PDF files are allowed'}), 400
        
        # Save uploaded file
        filename = secure_filename(file.filename)
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        pdf_path = os.path.join(app.config['UPLOAD_FOLDER'], f"{timestamp}_{filename}")
        
        print(f"Saving to: {pdf_path}")
        file.save(pdf_path)
        
        file_size_mb = os.path.getsize(pdf_path) / (1024 * 1024)
        print(f"File saved: {file_size_mb:.2f} MB")
        
        # Generate output filename
        output_filename = f"{timestamp}_audiobook.mp3"
        
        # Process PDF
        print("Starting PDF processing...")
        output_path = process_pdf(pdf_path, output_filename)
        
        # Clean up uploaded PDF
        try:
            os.remove(pdf_path)
        except:
            pass
        
        # Get output file size
        output_size = os.path.getsize(output_path) / (1024 * 1024)
        print(f"✅ Output file created: {output_size:.2f} MB")
        
        return jsonify({
            'success': True,
            'filename': output_filename,
            'size': f"{output_size:.2f} MB",
            'download_url': f'/download/{output_filename}'
        })
    
    except Exception as e:
        print(f"❌ ERROR: {str(e)}")
        print(traceback.format_exc())
        return jsonify({'error': str(e)}), 500

@app.route('/download/<filename>')
def download_file(filename):
    file_path = os.path.join(app.config['OUTPUT_FOLDER'], filename)
    if os.path.exists(file_path):
        return send_file(file_path, mimetype='audio/mpeg', as_attachment=False)
    return jsonify({'error': 'File not found'}), 404

@app.route('/test')
def test():
    return jsonify({
        'status': 'Server is running!',
        'tts_engine': 'Google TTS',
        'folders_exist': {
            'uploads': os.path.exists(UPLOAD_FOLDER),
            'outputs': os.path.exists(OUTPUT_FOLDER),
        }
    })

if __name__ == '__main__':
    print("=" * 60)
    print("🎙️  AI Voice Research - PDF to Speech Server")
    print("=" * 60)
    print("✅ Using Google TTS - No API limits!")
    print(f"📁 Upload folder: {os.path.abspath(UPLOAD_FOLDER)}")
    print(f"📁 Output folder: {os.path.abspath(OUTPUT_FOLDER)}")
    print("=" * 60)
    
    port = int(os.environ.get('PORT', 5000))
    print(f"🌐 Server running on port: {port}")
    print("=" * 60)
    
    app.run(debug=False, host='0.0.0.0', port=port)